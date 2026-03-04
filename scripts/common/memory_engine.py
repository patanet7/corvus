"""Hybrid memory search engine — BM25 (FTS5) + Cognee knowledge graph.

Two search layers:
- Layer 1: BM25 via SQLite FTS5 — fast keyword matching
- Layer 2: Cognee knowledge graph — entity/relationship-based recall (+ its own vectors via LanceDB)

If standalone embeddings are ever needed, Ollama runs on laptop-server locally.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.common.cognee_engine import CogneeEngine, GraphResult

if TYPE_CHECKING:
    from scripts.common.vault_writer import VaultWriter

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    content: str
    file_path: str
    score: float
    created_at: str
    chunk_id: int | None = None
    domain: str = "shared"
    visibility: str = "shared"


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize database schema (idempotent)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            file_path TEXT NOT NULL,
            chunk_index INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content, file_path,
            content='chunks', content_rowid='id'
        );

        CREATE TABLE IF NOT EXISTS embedding_cache (
            chunk_id INTEGER PRIMARY KEY,
            embedding BLOB,
            model_version TEXT
        );

        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            hash TEXT,
            last_indexed TEXT
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            summary TEXT,
            agent_name TEXT,
            tool_count INTEGER DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            agents_used TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            source TEXT,
            tags TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            importance REAL DEFAULT 0.5,
            session_id TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
    """)
    conn.commit()

    # Idempotent migration: add agents_used column to sessions if missing
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN agents_used TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Idempotent migration: add domain + visibility columns to chunks
    for col, default in [("domain", "shared"), ("visibility", "shared")]:
        try:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default}'")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Idempotent migration: add domain + visibility columns to memories
    for col, default in [("domain", "shared"), ("visibility", "shared")]:
        try:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default}'")
            conn.commit()
        except sqlite3.OperationalError:
            pass


class MemoryEngine:
    """Hybrid search engine with BM25 + Cognee knowledge graph and temporal decay.

    Args:
        agent_name: The owning agent's name, injected by the gateway at
            construction time.  When set, ``search()`` automatically
            enforces visibility so only shared memories and private
            memories belonging to this agent's readable domains are
            returned.  ``None`` disables filtering (backward compat).
    """

    def __init__(
        self,
        db_path: Path | str,
        cognee_enabled: bool = True,
        decay_half_life_days: float = 30.0,
        vault_writer: VaultWriter | None = None,
        cognee_data_dir: Path | str | None = None,
        agent_name: str | None = None,
    ):
        self.db_path = str(db_path)
        self.agent_name = agent_name
        self.cognee_enabled = cognee_enabled
        self.decay_half_life_days = decay_half_life_days
        self._vault_writer = vault_writer
        self._cognee = CogneeEngine(data_dir=cognee_data_dir)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def start_session(self, session_id: str, user: str, started_at: datetime) -> None:
        """Insert a new session row."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO sessions (id, user, started_at) VALUES (?, ?, ?)",
                (session_id, user, started_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def end_session(
        self,
        session_id: str,
        ended_at: datetime,
        summary: str | None = None,
        message_count: int = 0,
        tool_count: int = 0,
        agents_used: list[str] | None = None,
    ) -> None:
        """Update a session with final stats."""
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE sessions
                   SET ended_at = ?, summary = ?, message_count = ?,
                       tool_count = ?, agents_used = ?
                   WHERE id = ?""",
                (
                    ended_at.isoformat(),
                    summary,
                    message_count,
                    tool_count,
                    ",".join(agents_used or []),
                    session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_filter: str | None = None,
        user: str | None = None,
    ) -> list[dict]:
        """List sessions, optionally filtered by agent and/or user, newest first.

        Returns a list of dicts with session metadata.
        """
        conn = self._connect()
        try:
            sql = "SELECT * FROM sessions"
            conditions: list[str] = []
            params: list = []

            if agent_filter:
                conditions.append("agents_used LIKE ?")
                params.append(f"%{agent_filter}%")

            if user:
                conditions.append("user = ?")
                params.append(user)

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [self._session_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_session(self, session_id: str) -> dict | None:
        """Get a single session by ID, or None if not found."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            return self._session_row_to_dict(row)
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> None:
        """Delete a session by ID."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()

    def rename_session(self, session_id: str, name: str) -> None:
        """Rename a session (updates the summary field as display name)."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE sessions SET summary = ? WHERE id = ?",
                (name, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _session_row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sessions table row to a serializable dict."""
        agents_raw = row["agents_used"] or ""
        agents_list = [a for a in agents_raw.split(",") if a]
        return {
            "id": row["id"],
            "user": row["user"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "summary": row["summary"],
            "message_count": row["message_count"] or 0,
            "tool_count": row["tool_count"] or 0,
            "agents_used": agents_list,
        }

    @staticmethod
    def session_to_markdown(session: dict) -> str:
        """Export a session dict to Markdown format."""
        title = session.get("summary") or f"Session {session['id'][:8]}"
        lines = [
            f"# {title}",
            "",
            f"**Session ID:** {session['id']}",
            f"**User:** {session['user']}",
            f"**Started:** {session['started_at']}",
            f"**Ended:** {session.get('ended_at') or 'In progress'}",
            f"**Messages:** {session['message_count']}",
            f"**Tool calls:** {session['tool_count']}",
            f"**Agents:** {', '.join(session['agents_used']) or 'none'}",
            "",
        ]
        return "\n".join(lines)

    def search(self, query: str, limit: int = 10, domain: str | None = None) -> list[SearchResult]:
        """Search memories using BM25 + Cognee knowledge graph."""
        conn = self._connect()
        try:
            # Layer 1: BM25 keyword search
            merged = self._bm25_search(conn, query, limit * 2)

            # Layer 2: Cognee knowledge graph (never breaks BM25)
            if self.cognee_enabled and self._cognee.is_available:
                graph_results = self._cognee_search(query, domain, limit * 2)
                if graph_results:
                    merged = self._merge_results(merged, graph_results)

            # Apply temporal decay
            decayed = self._apply_temporal_decay(merged)

            # Sort by final score descending
            decayed.sort(key=lambda r: r.score, reverse=True)

            return decayed[:limit]
        finally:
            conn.close()

    def _cognee_search(self, query: str, domain: str | None, limit: int) -> list[SearchResult]:
        """Query Cognee knowledge graph, converting results to SearchResult."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    graph_results = pool.submit(
                        asyncio.run,
                        self._cognee.search(query, domain=domain, limit=limit),
                    ).result(timeout=10)
            else:
                graph_results = asyncio.run(self._cognee.search(query, domain=domain, limit=limit))
        except Exception:
            logger.debug("Cognee search failed — falling back to BM25+vector only", exc_info=True)
            return []

        return [self._graph_result_to_search_result(gr) for gr in graph_results]

    @staticmethod
    def _graph_result_to_search_result(gr: GraphResult) -> SearchResult:
        """Convert a Cognee GraphResult to a SearchResult."""
        return SearchResult(
            content=gr.content,
            file_path=gr.file_path,
            score=gr.score,
            created_at=gr.created_at,
            chunk_id=None,
        )

    def _bm25_search(self, conn: sqlite3.Connection, query: str, limit: int) -> list[SearchResult]:
        """Full-text search via SQLite FTS5 with visibility enforcement."""
        # Escape special FTS5 characters
        safe_query = query.replace('"', '""')
        try:
            sql = """
                SELECT c.id, c.content, c.file_path, c.created_at,
                       c.domain, c.visibility, rank AS bm25_score
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.rowid = c.id
                WHERE chunks_fts MATCH ?
            """
            params: list = [safe_query]

            # Visibility filtering based on injected agent_name
            if self.agent_name is not None:
                readable = [self.agent_name, "shared"]
                placeholders = ",".join("?" for _ in readable)
                sql += f" AND (c.visibility = 'shared' OR (c.visibility = 'private' AND c.domain IN ({placeholders})))"
                params.extend(readable)

            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # FTS5 MATCH can fail on certain query syntax — fall back to empty
            return []

        results = []
        for row in rows:
            # FTS5 rank is negative (lower = better), normalize to 0-1
            raw_score = abs(row["bm25_score"]) if row["bm25_score"] else 0.0
            score = min(raw_score / 10.0, 1.0)  # rough normalization
            results.append(
                SearchResult(
                    content=row["content"],
                    file_path=row["file_path"],
                    score=score,
                    created_at=row["created_at"] or "",
                    chunk_id=row["id"],
                    domain=row["domain"] or "shared",
                    visibility=row["visibility"] or "shared",
                )
            )
        return results

    def _merge_results(
        self,
        bm25: list[SearchResult],
        vec: list[SearchResult],
    ) -> list[SearchResult]:
        """Merge BM25 and vector results using MMR (Maximal Marginal Relevance)."""
        seen_ids: set[int] = set()
        merged: list[SearchResult] = []

        # Combine, preferring higher scores, deduplicating by chunk_id
        all_results = sorted(bm25 + vec, key=lambda r: r.score, reverse=True)
        for r in all_results:
            key = r.chunk_id or id(r)
            if key not in seen_ids:
                seen_ids.add(key)
                merged.append(r)

        return merged

    def _apply_temporal_decay(self, results: list[SearchResult]) -> list[SearchResult]:
        """Apply exponential temporal decay to scores."""
        now = datetime.now(UTC)
        decay_constant = math.log(2) / self.decay_half_life_days

        decayed = []
        for r in results:
            try:
                created = datetime.fromisoformat(r.created_at.replace("Z", "+00:00"))
                age_days = (now - created).total_seconds() / 86400
                decay_factor = math.exp(-decay_constant * age_days)
            except (ValueError, TypeError):
                decay_factor = 0.5  # unknown age gets middle weight

            decayed.append(
                SearchResult(
                    content=r.content,
                    file_path=r.file_path,
                    score=r.score * decay_factor,
                    created_at=r.created_at,
                    chunk_id=r.chunk_id,
                    domain=r.domain,
                    visibility=r.visibility,
                )
            )
        return decayed

    def save(
        self,
        content: str,
        file_path: str,
        tags: list[str] | None = None,
        domain: str | None = None,
        content_type: str | None = None,
        title: str | None = None,
        importance: float = 0.5,
        aliases: list[str] | None = None,
        session_id: str | None = None,
        visibility: str = "private",
    ) -> int:
        """Save a memory chunk: write to vault (if configured), then index in SQLite.

        Args:
            visibility: "private" (owner-agent only) or "shared" (all agents).
                Agents choose this at save time; the gateway injects
                ``agent_name`` at construction time for read-side enforcement.

        When a VaultWriter is attached, the file is written to the Obsidian vault
        first and the vault path becomes the canonical ``file_path`` in SQLite.
        """
        now = datetime.now(UTC)
        effective_domain = domain or "shared"

        # Write to Obsidian vault if writer is configured and domain is given
        if self._vault_writer and domain:
            vault_path = self._vault_writer.save_to_vault(
                content=content,
                domain=domain,
                tags=tags,
                aliases=aliases,
                importance=importance,
                content_type=content_type,
                title=title,
                created=now,
            )
            file_path = str(vault_path)

        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT INTO chunks (content, file_path, chunk_index, created_at, domain, visibility) "
                "VALUES (?, ?, 0, ?, ?, ?)",
                (content, file_path, now.isoformat(), effective_domain, visibility),
            )
            chunk_id = cursor.lastrowid
            if chunk_id is None:
                raise RuntimeError("INSERT should always return a rowid")

            # Update FTS index
            conn.execute(
                "INSERT INTO chunks_fts(rowid, content, file_path) VALUES (?, ?, ?)",
                (chunk_id, content, file_path),
            )

            # Persist to memories table (links to session via FK)
            conn.execute(
                """INSERT INTO memories
                   (content, source, tags, created_at, importance, session_id, domain, visibility)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    content,
                    file_path,
                    ",".join(tags or []),
                    now.isoformat(),
                    importance,
                    session_id,
                    effective_domain,
                    visibility,
                ),
            )
            conn.commit()

            # Index into Cognee knowledge graph (fire-and-forget)
            if self.cognee_enabled and self._cognee.is_available and domain:
                try:
                    asyncio.run(self._cognee.index(content, domain))
                except Exception:
                    logger.debug(
                        "Cognee indexing failed — memory saved to SQLite only",
                        exc_info=True,
                    )

            return chunk_id
        finally:
            conn.close()
