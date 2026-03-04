"""One-time migration from old MemoryEngine schema to MemoryHub (FTS5Backend) schema.

Old schema tables: chunks, chunks_fts, embedding_cache, files, meta, memories (old), sessions
New schema tables: memories (new), memories_fts, memory_audit, sessions (kept)

Usage:
    python -m scripts.migrate_memory_schema [--db-path data/memory.sqlite]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# New schema — matches claw/memory/backends/fts5.py _SCHEMA exactly.
# Kept as a list of individual statements (not a single string) so each can be
# executed with conn.execute() inside an explicit transaction.  Splitting a
# single string on ";" would break CREATE TRIGGER bodies that contain ";".
_NEW_SCHEMA_STATEMENTS: list[str] = [
    """CREATE TABLE IF NOT EXISTS memories (
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
)""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, domain, tags,
    content='memories', content_rowid='id'
)""",
    """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END""",
    """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
END""",
    """CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END""",
    """CREATE TABLE IF NOT EXISTS memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    agent_name TEXT,
    operation TEXT NOT NULL,
    record_id TEXT,
    domain TEXT,
    visibility TEXT,
    details TEXT
)""",
]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the database."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row[0] > 0


_SAFE_TABLE_NAMES = frozenset(
    {
        "chunks",
        "memories",
        "sessions",
        "chunks_fts",
        "memories_fts",
        "embedding_cache",
        "files",
        "meta",
        "memory_audit",
    }
)


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table.

    Uses allowlist for table_name since PRAGMA doesn't support parameterized queries.
    """
    if table_name not in _SAFE_TABLE_NAMES:
        raise ValueError(f"Unexpected table name: {table_name!r}")
    cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(col[1] == column_name for col in cols)


def _is_old_memories_schema(conn: sqlite3.Connection) -> bool:
    """Detect old memories table: has integer PK and session_id, no record_id."""
    if not _table_exists(conn, "memories"):
        return False
    if _has_column(conn, "memories", "record_id"):
        return False  # Already new schema
    if _has_column(conn, "memories", "session_id"):
        return True  # Old schema with session FK
    # Old schema without session_id but with expires_at
    if _has_column(conn, "memories", "expires_at"):
        return True
    return False


def migrate(db_path: Path | str) -> dict:
    """Run the schema migration.

    Returns a dict summarizing what was migrated:
        {
            "chunks_migrated": int,
            "memories_migrated": int,
            "tables_dropped": list[str],
            "backup_path": str | None,
        }
    """
    db_path = Path(db_path)
    result = {
        "chunks_migrated": 0,
        "memories_migrated": 0,
        "tables_dropped": [],
        "backup_path": None,
    }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        has_chunks = _table_exists(conn, "chunks")
        has_old_memories = _is_old_memories_schema(conn)

        if not has_chunks and not has_old_memories:
            # Nothing to migrate — either already new schema or empty DB
            conn.close()
            return result

        # Create backup before any destructive operations
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        backup_path = db_path.parent / f"{db_path.name}.bak.{timestamp}"
        conn.close()
        shutil.copy2(str(db_path), str(backup_path))
        result["backup_path"] = str(backup_path)

        conn = sqlite3.connect(str(db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        # Collect data from old tables before dropping them
        chunks_data = []
        if has_chunks:
            # Read all chunks. The columns may vary (domain/visibility added via ALTER)
            chunk_cols = {col[1] for col in conn.execute("PRAGMA table_info(chunks)").fetchall()}
            rows = conn.execute("SELECT * FROM chunks").fetchall()
            for row in rows:
                record = {
                    "content": row["content"],
                    "created_at": row["created_at"] or datetime.now(UTC).isoformat(),
                    "domain": row["domain"] if "domain" in chunk_cols else "shared",
                    "visibility": row["visibility"] if "visibility" in chunk_cols else "shared",
                    "source": "migrated_chunk",
                    "importance": 0.5,
                    "tags": "",
                    "metadata": "{}",
                }
                chunks_data.append(record)
            result["chunks_migrated"] = len(chunks_data)

        old_memories_data = []
        if has_old_memories:
            mem_cols = {col[1] for col in conn.execute("PRAGMA table_info(memories)").fetchall()}
            rows = conn.execute("SELECT * FROM memories").fetchall()
            for row in rows:
                record = {
                    "content": row["content"],
                    "created_at": row["created_at"] or datetime.now(UTC).isoformat(),
                    "domain": row["domain"] if "domain" in mem_cols else "shared",
                    "visibility": row["visibility"] if "visibility" in mem_cols else "shared",
                    "source": "migrated_memory",
                    "importance": row["importance"] if "importance" in mem_cols else 0.5,
                    "tags": row["tags"] if "tags" in mem_cols else "",
                    "metadata": "{}",
                }
                old_memories_data.append(record)
            result["memories_migrated"] = len(old_memories_data)

        # All destructive ops in a single transaction to prevent data loss.
        # Data was already collected above; backup exists on disk.
        # NOTE: executescript() auto-commits so we avoid it — use execute()
        # for each statement within a single BEGIN/COMMIT block.
        conn.execute("BEGIN IMMEDIATE")
        try:
            tables_to_drop = []
            for table_name in ["chunks_fts", "chunks", "embedding_cache", "files", "meta"]:
                if _table_exists(conn, table_name):
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                    tables_to_drop.append(table_name)

            if has_old_memories:
                if _table_exists(conn, "memories_fts"):
                    conn.execute("DROP TABLE IF EXISTS memories_fts")
                    tables_to_drop.append("memories_fts")
                conn.execute("DROP TABLE IF EXISTS memories")
                tables_to_drop.append("memories")

            result["tables_dropped"] = tables_to_drop

            # Create new schema — each statement executed individually to stay
            # inside our explicit transaction (executescript would auto-commit).
            for statement in _NEW_SCHEMA_STATEMENTS:
                conn.execute(statement)

            # Insert migrated data — triggers auto-populate memories_fts
            all_records = chunks_data + old_memories_data
            for record in all_records:
                record_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO memories "
                    "(record_id, content, domain, visibility, importance, tags, "
                    "source, created_at, updated_at, deleted_at, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record_id,
                        record["content"],
                        record["domain"],
                        record["visibility"],
                        record["importance"],
                        record["tags"],
                        record["source"],
                        record["created_at"],
                        None,  # updated_at
                        None,  # deleted_at
                        record["metadata"],
                    ),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    finally:
        conn.close()

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate old MemoryEngine schema to MemoryHub schema",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/memory.sqlite"),
        help="Path to the SQLite database (default: data/memory.sqlite)",
    )
    args = parser.parse_args()

    if not args.db_path.exists():
        print(f"Database not found: {args.db_path}")
        sys.exit(1)

    print(f"Migrating {args.db_path} ...")
    result = migrate(args.db_path)

    print(f"  Chunks migrated:   {result['chunks_migrated']}")
    print(f"  Memories migrated: {result['memories_migrated']}")
    print(f"  Tables dropped:    {', '.join(result['tables_dropped']) or 'none'}")
    if result["backup_path"]:
        print(f"  Backup created:    {result['backup_path']}")
    print("Done.")


if __name__ == "__main__":
    main()
