"""SQLite FTS5 primary backend — consolidated from SQLiteFTS5Backend + MemoryEngine.

This is the always-on primary backend. All writes land here first. Source of truth.
Uses BM25 text search via SQLite FTS5 with visibility filtering at the SQL level.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from corvus.memory.backends.protocol import HealthStatus
from corvus.memory.record import MemoryRecord

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'shared',
    visibility TEXT NOT NULL DEFAULT 'private'
        CHECK(visibility IN ('private', 'shared')),
    importance REAL NOT NULL DEFAULT 0.5,
    tags TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'agent',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    deleted_at TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, domain, tags,
    content='memories', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END;

CREATE TABLE IF NOT EXISTS memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    agent_name TEXT,
    operation TEXT NOT NULL,
    record_id TEXT,
    domain TEXT,
    visibility TEXT,
    details TEXT
);
"""

_MEMORIES_AU_TRIGGER = """\
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END;
"""


def _parse_tags(raw: str) -> list[str]:
    """Parse comma-separated tags string into a list."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _join_tags(tags: list[str]) -> str:
    """Join tag list into comma-separated string for storage."""
    return ",".join(tags)


class FTS5Backend:
    """SQLite FTS5 primary backend with BM25 search and visibility filtering.

    Implements the MemoryBackend protocol. Designed to be the always-on
    primary backend in the Hub's primary + overlay architecture.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create schema if it doesn't exist. Sets WAL mode."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            self._migrate_legacy_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        """Apply additive migrations for legacy memories schema variants."""
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
        if not columns:
            return

        # Legacy rows may predate FTS shadow rows; avoid update-trigger writes
        # while backfilling additive columns.
        conn.execute("DROP TRIGGER IF EXISTS memories_au")
        if "record_id" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN record_id TEXT")
            columns.add("record_id")
        # Backfill deterministic IDs for pre-migration rows.
        conn.execute("UPDATE memories SET record_id = printf('legacy-%d', id) WHERE record_id IS NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_record_id ON memories(record_id)")

        if "updated_at" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN updated_at TEXT")
            columns.add("updated_at")

        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN deleted_at TEXT")
            columns.add("deleted_at")

        if "metadata" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN metadata TEXT")
            columns.add("metadata")
        conn.execute("UPDATE memories SET metadata = '{}' WHERE metadata IS NULL OR TRIM(metadata) = ''")
        conn.executescript(_MEMORIES_AU_TRIGGER)

    def _connect(self) -> sqlite3.Connection:
        """Get a connection with WAL mode enabled."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def save(self, record: MemoryRecord) -> str:
        """Save a memory record. Returns the record_id."""
        return await asyncio.to_thread(self._save_sync, record)

    def _save_sync(self, record: MemoryRecord) -> str:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO memories "
                "(record_id, content, domain, visibility, importance, tags, "
                "source, created_at, updated_at, deleted_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.content,
                    record.domain,
                    record.visibility,
                    record.importance,
                    _join_tags(record.tags),
                    record.source,
                    record.created_at,
                    record.updated_at,
                    record.deleted_at,
                    json.dumps(record.metadata),
                ),
            )
            conn.commit()
            return record.id
        finally:
            conn.close()

    async def update(self, record: MemoryRecord) -> bool:
        """Update an existing memory record."""
        return await asyncio.to_thread(self._update_sync, record)

    def _update_sync(self, record: MemoryRecord) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE memories "
                "SET content = ?, domain = ?, visibility = ?, importance = ?, tags = ?, "
                "updated_at = ?, metadata = ? "
                "WHERE record_id = ? AND deleted_at IS NULL",
                (
                    record.content,
                    record.domain,
                    record.visibility,
                    record.importance,
                    _join_tags(record.tags),
                    record.updated_at,
                    json.dumps(record.metadata),
                    record.id,
                ),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain: str | None = None,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Search with BM25 ranking and visibility filtering."""
        return await asyncio.to_thread(
            self._search_sync,
            query,
            limit,
            domain,
            readable_domains,
        )

    def _search_sync(
        self,
        query: str,
        limit: int,
        domain: str | None,
        readable_domains: list[str] | None,
    ) -> list[MemoryRecord]:
        conn = self._connect()
        try:
            # Build query with visibility filtering
            sql = (
                "SELECT m.record_id, m.content, m.domain, m.visibility, "
                "m.importance, m.tags, m.source, m.created_at, m.updated_at, "
                "m.deleted_at, m.metadata, -rank AS score "
                "FROM memories_fts f "
                "JOIN memories m ON f.rowid = m.id "
                "WHERE memories_fts MATCH ? "
                "AND m.deleted_at IS NULL "
            )
            params: list = [query]

            # Visibility filtering
            if readable_domains is not None:
                placeholders = ",".join("?" for _ in readable_domains)
                sql += f"AND (m.visibility = 'shared' OR (m.visibility = 'private' AND m.domain IN ({placeholders}))) "
                params.extend(readable_domains)

            # Domain filter
            if domain is not None:
                sql += "AND m.domain = ? "
                params.append(domain)

            sql += "ORDER BY score DESC LIMIT ?"
            params.append(limit)

            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # FTS5 query syntax error — return empty
                return []

            return [
                MemoryRecord(
                    id=row[0],
                    content=row[1],
                    domain=row[2],
                    visibility=row[3],
                    importance=row[4],
                    tags=_parse_tags(row[5]),
                    source=row[6],
                    created_at=row[7],
                    updated_at=row[8],
                    deleted_at=row[9],
                    metadata=json.loads(row[10]) if row[10] else {},
                    score=float(row[11]) if row[11] else 0.0,
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Get a single record by ID. Excludes soft-deleted."""
        return await asyncio.to_thread(self._get_sync, record_id)

    def _get_sync(self, record_id: str) -> MemoryRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT record_id, content, domain, visibility, importance, "
                "tags, source, created_at, updated_at, deleted_at, metadata "
                "FROM memories WHERE record_id = ? AND deleted_at IS NULL",
                (record_id,),
            ).fetchone()
            if row is None:
                return None
            return MemoryRecord(
                id=row[0],
                content=row[1],
                domain=row[2],
                visibility=row[3],
                importance=row[4],
                tags=_parse_tags(row[5]),
                source=row[6],
                created_at=row[7],
                updated_at=row[8],
                deleted_at=row[9],
                metadata=json.loads(row[10]) if row[10] else {},
            )
        finally:
            conn.close()

    async def list_memories(
        self,
        *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """List memories with pagination and visibility filtering."""
        return await asyncio.to_thread(
            self._list_sync,
            domain,
            limit,
            offset,
            readable_domains,
        )

    def _list_sync(
        self,
        domain: str | None,
        limit: int,
        offset: int,
        readable_domains: list[str] | None,
    ) -> list[MemoryRecord]:
        conn = self._connect()
        try:
            sql = (
                "SELECT record_id, content, domain, visibility, importance, "
                "tags, source, created_at, updated_at, deleted_at, metadata "
                "FROM memories WHERE deleted_at IS NULL "
            )
            params: list = []

            if readable_domains is not None:
                placeholders = ",".join("?" for _ in readable_domains)
                sql += f"AND (visibility = 'shared' OR (visibility = 'private' AND domain IN ({placeholders}))) "
                params.extend(readable_domains)

            if domain is not None:
                sql += "AND domain = ? "
                params.append(domain)

            sql += "ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [
                MemoryRecord(
                    id=row[0],
                    content=row[1],
                    domain=row[2],
                    visibility=row[3],
                    importance=row[4],
                    tags=_parse_tags(row[5]),
                    source=row[6],
                    created_at=row[7],
                    updated_at=row[8],
                    deleted_at=row[9],
                    metadata=json.loads(row[10]) if row[10] else {},
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def forget(self, record_id: str) -> bool:
        """Soft-delete by setting deleted_at. Returns True if record existed."""
        return await asyncio.to_thread(self._forget_sync, record_id)

    def _forget_sync(self, record_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE memories SET deleted_at = ? WHERE record_id = ? AND deleted_at IS NULL",
                (now, record_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    async def health_check(self) -> HealthStatus:
        """Check database health."""
        return await asyncio.to_thread(self._health_sync)

    def _health_sync(self) -> HealthStatus:
        try:
            conn = self._connect()
            try:
                conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                return HealthStatus(name="fts5-primary", status="healthy")
            finally:
                conn.close()
        except Exception as e:
            return HealthStatus(
                name="fts5-primary",
                status="unhealthy",
                detail=str(e),
            )

    def write_audit(
        self,
        agent_name: str,
        operation: str,
        record_id: str | None,
        domain: str | None,
        visibility: str | None,
    ) -> None:
        """Write an audit event. Uses WAL-mode connection."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO memory_audit "
                "(timestamp, agent_name, operation, record_id, domain, visibility) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(),
                    agent_name,
                    operation,
                    record_id,
                    domain,
                    visibility,
                ),
            )
            conn.commit()
        finally:
            conn.close()
