"""Behavioral tests for session tracking — MemoryEngine.start_session / end_session.

All tests use real SQLite databases. NO mocks, NO monkeypatch, NO @patch.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.common.memory_engine import MemoryEngine, init_db


@pytest.fixture
def engine(tmp_path: Path) -> MemoryEngine:
    """Create a real MemoryEngine with a fresh SQLite database."""
    db_path = tmp_path / "session_test.db"
    conn = sqlite3.connect(str(db_path))
    init_db(conn)
    conn.close()
    return MemoryEngine(db_path=db_path, cognee_enabled=False)


@pytest.fixture
def db_conn(engine: MemoryEngine) -> sqlite3.Connection:
    """Return a raw connection for assertions (Row factory)."""
    conn = sqlite3.connect(engine.db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------------


class TestStartSession:
    """Tests for MemoryEngine.start_session()."""

    def test_start_session_creates_row(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """start_session inserts a session row with correct id, user, started_at."""
        now = datetime.now(UTC)
        engine.start_session("sess-001", "alice", now)

        row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-001",)).fetchone()
        assert row is not None
        assert row["user"] == "alice"
        assert row["started_at"] == now.isoformat()
        assert row["ended_at"] is None
        assert row["summary"] is None
        assert row["message_count"] == 0
        assert row["tool_count"] == 0

    def test_start_session_multiple_sessions(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """Multiple sessions can be created for the same user."""
        now = datetime.now(UTC)
        engine.start_session("sess-001", "alice", now)
        engine.start_session("sess-002", "alice", now)

        count = db_conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 2

    def test_start_session_different_users(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """Sessions for different users are stored independently."""
        now = datetime.now(UTC)
        engine.start_session("sess-a", "alice", now)
        engine.start_session("sess-b", "bob", now)

        alice_row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-a",)).fetchone()
        bob_row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-b",)).fetchone()
        assert alice_row["user"] == "alice"
        assert bob_row["user"] == "bob"

    def test_start_session_duplicate_id_raises(self, engine: MemoryEngine):
        """Inserting a session with duplicate id raises IntegrityError."""
        now = datetime.now(UTC)
        engine.start_session("dup-id", "alice", now)
        with pytest.raises(sqlite3.IntegrityError):
            engine.start_session("dup-id", "bob", now)


# ---------------------------------------------------------------------------
# end_session
# ---------------------------------------------------------------------------


class TestEndSession:
    """Tests for MemoryEngine.end_session()."""

    def test_end_session_updates_row(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """end_session updates ended_at, summary, message_count, tool_count, agents_used."""
        start = datetime(2026, 2, 26, 10, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 26, 10, 30, 0, tzinfo=UTC)

        engine.start_session("sess-end", "alice", start)
        engine.end_session(
            session_id="sess-end",
            ended_at=end,
            summary="Discussed homelab setup",
            message_count=12,
            tool_count=5,
            agents_used=["homelab", "personal"],
        )

        row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-end",)).fetchone()
        assert row["ended_at"] == end.isoformat()
        assert row["summary"] == "Discussed homelab setup"
        assert row["message_count"] == 12
        assert row["tool_count"] == 5
        assert row["agents_used"] == "homelab,personal"

    def test_end_session_without_summary(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """end_session works when summary is None."""
        now = datetime.now(UTC)
        engine.start_session("sess-nosum", "alice", now)
        engine.end_session(session_id="sess-nosum", ended_at=now)

        row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-nosum",)).fetchone()
        assert row["summary"] is None
        assert row["message_count"] == 0
        assert row["tool_count"] == 0
        assert row["agents_used"] == ""

    def test_end_session_empty_agents(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """end_session with empty agents_used stores empty string."""
        now = datetime.now(UTC)
        engine.start_session("sess-empty-agents", "alice", now)
        engine.end_session(session_id="sess-empty-agents", ended_at=now, agents_used=[])

        row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-empty-agents",)).fetchone()
        assert row["agents_used"] == ""

    def test_end_session_none_agents(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """end_session with agents_used=None stores empty string."""
        now = datetime.now(UTC)
        engine.start_session("sess-none-agents", "alice", now)
        engine.end_session(session_id="sess-none-agents", ended_at=now, agents_used=None)

        row = db_conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-none-agents",)).fetchone()
        assert row["agents_used"] == ""

    def test_end_session_nonexistent_id_is_noop(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """end_session on a nonexistent session_id silently does nothing."""
        now = datetime.now(UTC)
        # Should not raise
        engine.end_session(session_id="does-not-exist", ended_at=now)
        count = db_conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# agents_used column migration
# ---------------------------------------------------------------------------


class TestAgentsUsedMigration:
    """Tests that the agents_used column migration is idempotent."""

    def test_init_db_idempotent(self, tmp_path: Path):
        """Calling init_db twice does not raise on the agents_used ALTER TABLE."""
        db_path = tmp_path / "idempotent.db"
        conn = sqlite3.connect(str(db_path))

        # First init — creates table with agents_used column
        init_db(conn)
        # Second init — ALTER TABLE should silently fail (column exists)
        init_db(conn)

        # Verify the column exists by inserting a row that uses it
        conn.execute(
            "INSERT INTO sessions (id, user, started_at, agents_used) VALUES (?, ?, ?, ?)",
            ("test-id", "alice", datetime.now(UTC).isoformat(), "homelab,work"),
        )
        conn.commit()
        row = conn.execute("SELECT agents_used FROM sessions WHERE id = ?", ("test-id",)).fetchone()
        assert row[0] == "homelab,work"
        conn.close()

    def test_migration_on_old_schema(self, tmp_path: Path):
        """init_db adds agents_used column to a sessions table that lacks it."""
        db_path = tmp_path / "old_schema.db"
        conn = sqlite3.connect(str(db_path))

        # Create sessions table WITHOUT agents_used (simulating old schema)
        conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                summary TEXT,
                agent_name TEXT,
                tool_count INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0
            )
        """)
        conn.commit()

        # Also create other tables that init_db expects (to avoid duplicate table errors)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, content TEXT, file_path TEXT, chunk_index INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content, file_path, content='chunks', content_rowid='id')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS embedding_cache (chunk_id INTEGER PRIMARY KEY, embedding BLOB, model_version TEXT)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT, last_indexed TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("""CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL, source TEXT, tags TEXT,
            created_at TEXT NOT NULL, expires_at TEXT,
            importance REAL DEFAULT 0.5, session_id TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)")
        conn.commit()

        # Run init_db — should add agents_used column via ALTER TABLE
        init_db(conn)

        # Verify agents_used column is usable
        conn.execute(
            "INSERT INTO sessions (id, user, started_at, agents_used) VALUES (?, ?, ?, ?)",
            ("migrated", "bob", datetime.now(UTC).isoformat(), "finance"),
        )
        conn.commit()
        row = conn.execute("SELECT agents_used FROM sessions WHERE id = ?", ("migrated",)).fetchone()
        assert row[0] == "finance"
        conn.close()


# ---------------------------------------------------------------------------
# session_id FK on memories
# ---------------------------------------------------------------------------


class TestSessionMemoryFK:
    """Tests that memories saved with session_id link correctly to sessions."""

    def test_save_with_session_id(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """MemoryEngine.save() with session_id inserts a memories row with the FK."""
        now = datetime.now(UTC)
        engine.start_session("sess-mem", "alice", now)

        engine.save(
            content="User prefers dark mode",
            file_path="memory/2026-02-26.md",
            tags=["preference"],
            importance=0.4,
            session_id="sess-mem",
        )

        row = db_conn.execute("SELECT * FROM memories WHERE session_id = ?", ("sess-mem",)).fetchone()
        assert row is not None
        assert row["content"] == "User prefers dark mode"
        assert row["session_id"] == "sess-mem"
        assert row["importance"] == 0.4
        assert row["tags"] == "preference"

    def test_save_without_session_id(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """MemoryEngine.save() without session_id stores NULL in the FK column."""
        engine.save(
            content="A standalone memory",
            file_path="memory/standalone.md",
        )

        row = db_conn.execute("SELECT * FROM memories WHERE content = ?", ("A standalone memory",)).fetchone()
        assert row is not None
        assert row["session_id"] is None

    def test_multiple_memories_per_session(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """Multiple memories can be linked to the same session."""
        now = datetime.now(UTC)
        engine.start_session("sess-multi", "alice", now)

        for i in range(3):
            engine.save(
                content=f"Memory {i}",
                file_path=f"memory/m{i}.md",
                session_id="sess-multi",
            )

        rows = db_conn.execute("SELECT * FROM memories WHERE session_id = ?", ("sess-multi",)).fetchall()
        assert len(rows) == 3

    def test_join_session_to_memories(self, engine: MemoryEngine, db_conn: sqlite3.Connection):
        """Memories can be JOINed to sessions to get user and timing info."""
        start = datetime(2026, 2, 26, 10, 0, 0, tzinfo=UTC)
        engine.start_session("sess-join", "alice", start)
        engine.save(
            content="Homelab uses 4 hosts",
            file_path="memory/infra.md",
            session_id="sess-join",
        )

        row = db_conn.execute(
            """
            SELECT m.content, s.user, s.started_at
            FROM memories m
            JOIN sessions s ON m.session_id = s.id
            WHERE m.session_id = ?
        """,
            ("sess-join",),
        ).fetchone()
        assert row is not None
        assert row[0] == "Homelab uses 4 hosts"
        assert row[1] == "alice"
        assert row[2] == start.isoformat()


# ---------------------------------------------------------------------------
# SessionTranscript.session_id field
# ---------------------------------------------------------------------------


class TestSessionTranscriptField:
    """Tests that SessionTranscript has a session_id field."""

    def test_session_id_default_empty(self):
        """session_id defaults to empty string."""
        from corvus.session import SessionTranscript

        t = SessionTranscript(user="alice")
        assert t.session_id == ""

    def test_session_id_set_on_creation(self):
        """session_id can be set at creation time."""
        from corvus.session import SessionTranscript

        t = SessionTranscript(user="alice", session_id="abc-123")
        assert t.session_id == "abc-123"
