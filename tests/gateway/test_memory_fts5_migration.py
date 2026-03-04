"""Behavioral tests for FTS5 legacy schema migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from corvus.memory.backends.fts5 import FTS5Backend
from corvus.memory.record import MemoryRecord
from tests.conftest import run


def _create_legacy_memories_schema(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                source TEXT,
                tags TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                importance REAL DEFAULT 0.5,
                session_id TEXT,
                domain TEXT NOT NULL DEFAULT 'shared',
                visibility TEXT NOT NULL DEFAULT 'shared'
            );
            """
        )
        conn.execute(
            "INSERT INTO memories (content, source, tags, created_at, domain, visibility, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy memory row",
                "legacy",
                "legacy,seed",
                "2026-03-01T10:00:00+00:00",
                "shared",
                "shared",
                0.6,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_migrates_legacy_schema_and_supports_new_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-memory.sqlite"
    _create_legacy_memories_schema(db_path)

    backend = FTS5Backend(db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
        assert "record_id" in columns
        assert "updated_at" in columns
        assert "deleted_at" in columns
        assert "metadata" in columns
        legacy_record_id = conn.execute("SELECT record_id FROM memories WHERE id = 1").fetchone()[0]
        assert legacy_record_id == "legacy-1"
    finally:
        conn.close()

    row = MemoryRecord(
        id="migration-new-1",
        content="new schema write after migration",
        domain="shared",
        visibility="shared",
        importance=0.5,
        tags=["migration"],
        source="test",
        created_at="2026-03-02T08:00:00+00:00",
        metadata={"source": "migration-test"},
    )
    run(backend.save(row))
    fetched = run(backend.get("migration-new-1"))
    assert fetched is not None
    assert fetched.content == "new schema write after migration"
