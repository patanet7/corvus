"""Behavioral tests for old MemoryEngine → MemoryHub schema migration.

No mocks. Real SQLite databases in tmp_path, real migration, real verification.
"""

import sqlite3
import uuid


class TestSchemaMigration:
    """Test the migrate() function converts old schema to new MemoryHub schema."""

    def _seed_old_schema(self, db_path, *, with_memories: bool = False, with_sessions: bool = False):
        """Create a database with the old MemoryEngine schema and seed data."""
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                file_path TEXT NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                domain TEXT NOT NULL DEFAULT 'shared',
                visibility TEXT NOT NULL DEFAULT 'shared'
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
        """)

        if with_sessions:
            conn.execute("""
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
                )
            """)
            conn.execute(
                "INSERT INTO sessions VALUES ('s1', 'thomas', '2026-01-01T00:00:00', NULL, 'test', NULL, 0, 0, '')"
            )

        if with_memories:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
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
                )
            """)
            conn.execute(
                "INSERT INTO memories (content, source, tags, created_at, importance, domain, visibility) "
                "VALUES ('Old memory content', 'agent', 'tag1,tag2', '2026-01-15T00:00:00', 0.7, 'work', 'private')"
            )

        conn.commit()
        conn.close()

    def test_migrates_chunks_to_memories(self, tmp_path):
        """Chunks from old schema become memories in new schema."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at, domain, visibility) "
            "VALUES ('Test chunk content', '/vault/notes/test.md', '2026-01-01T00:00:00', 'shared', 'shared')"
        )
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at, domain, visibility) "
            "VALUES ('Second chunk', '/vault/notes/other.md', '2026-01-02T00:00:00', 'work', 'private')"
        )
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        result = migrate(db_path)

        assert result["chunks_migrated"] == 2

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT record_id, content, domain, visibility, source, importance FROM memories"
        ).fetchall()
        assert len(rows) == 2

        # Verify fields mapped correctly
        contents = {r[1] for r in rows}
        assert "Test chunk content" in contents
        assert "Second chunk" in contents

        # Verify record_id is a valid UUID
        for row in rows:
            uuid.UUID(row[0])  # Raises if invalid

        # Verify source is tagged as migrated
        for row in rows:
            assert row[4] == "migrated_chunk"

        # Old tables should be gone
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "chunks" not in tables
        assert "chunks_fts" not in tables
        assert "embedding_cache" not in tables
        assert "files" not in tables
        assert "meta" not in tables
        assert "memories" in tables
        assert "memories_fts" in tables
        conn.close()

    def test_migrates_old_memories_table(self, tmp_path):
        """Old memories table (integer PK, session_id FK) gets migrated too."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path, with_memories=True)

        from scripts.migrate_memory_schema import migrate

        result = migrate(db_path)

        assert result["memories_migrated"] == 1

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT record_id, content, domain, visibility, tags, importance, source FROM memories"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "Old memory content"
        assert rows[0][2] == "work"
        assert rows[0][3] == "private"
        assert rows[0][4] == "tag1,tag2"
        assert rows[0][5] == 0.7
        assert rows[0][6] == "migrated_memory"
        conn.close()

    def test_migrates_both_chunks_and_memories(self, tmp_path):
        """Both chunks and old memories get migrated into the new memories table."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path, with_memories=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at) "
            "VALUES ('Chunk data', '/vault/chunk.md', '2026-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        result = migrate(db_path)

        assert result["chunks_migrated"] == 1
        assert result["memories_migrated"] == 1

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT content FROM memories").fetchall()
        assert len(rows) == 2
        conn.close()

    def test_creates_backup(self, tmp_path):
        """Migration creates a timestamped backup before modifying the DB."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at) VALUES ('backup test', '/test.md', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        migrate(db_path)

        backups = list(tmp_path.glob("memory.sqlite.bak.*"))
        assert len(backups) == 1

        # Backup should be a valid SQLite DB with old schema
        bak_conn = sqlite3.connect(str(backups[0]))
        tables = [r[0] for r in bak_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "chunks" in tables
        bak_conn.close()

    def test_noop_when_no_old_schema(self, tmp_path):
        """If DB already has new schema (no chunks table), migration is a no-op."""
        db_path = tmp_path / "memory.sqlite"
        conn = sqlite3.connect(str(db_path))
        # Create the new schema directly
        conn.executescript("""
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT 'shared',
                visibility TEXT NOT NULL DEFAULT 'private',
                importance REAL NOT NULL DEFAULT 0.5,
                tags TEXT DEFAULT '',
                source TEXT NOT NULL DEFAULT 'agent',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                deleted_at TEXT,
                metadata TEXT DEFAULT '{}'
            );
        """)
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        result = migrate(db_path)
        assert result["chunks_migrated"] == 0
        assert result["memories_migrated"] == 0

    def test_preserves_sessions_table(self, tmp_path):
        """Sessions table survives migration — it's still used by the system."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path, with_sessions=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO chunks (content, file_path, created_at) VALUES ('test', '/t.md', '2026-01-01')")
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1

        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "sessions" in tables
        conn.close()

    def test_fts_index_works_after_migration(self, tmp_path):
        """After migration, FTS5 full-text search works on migrated data."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at) "
            "VALUES ('Python asyncio tutorial notes', '/vault/python.md', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at) "
            "VALUES ('Kubernetes deployment guide', '/vault/k8s.md', '2026-01-02')"
        )
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        # FTS5 search should work
        results = conn.execute(
            "SELECT m.content FROM memories_fts f JOIN memories m ON f.rowid = m.id WHERE memories_fts MATCH 'asyncio'"
        ).fetchall()
        assert len(results) == 1
        assert "asyncio" in results[0][0]
        conn.close()

    def test_creates_audit_table(self, tmp_path):
        """Migration creates the memory_audit table for the new schema."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO chunks (content, file_path, created_at) VALUES ('test', '/t.md', '2026-01-01')")
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "memory_audit" in tables
        conn.close()

    def test_creates_triggers(self, tmp_path):
        """Migration creates FTS sync triggers (insert, update, delete)."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO chunks (content, file_path, created_at) VALUES ('test', '/t.md', '2026-01-01')")
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        triggers = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]
        assert "memories_ai" in triggers
        assert "memories_ad" in triggers
        assert "memories_au" in triggers
        conn.close()

    def test_empty_database_with_chunks_table(self, tmp_path):
        """Migration handles an old schema with zero rows gracefully."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        from scripts.migrate_memory_schema import migrate

        result = migrate(db_path)
        assert result["chunks_migrated"] == 0
        assert result["memories_migrated"] == 0

        # Old tables should still be cleaned up
        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "chunks" not in tables
        assert "memories" in tables
        conn.close()

    def test_preserves_domain_and_visibility(self, tmp_path):
        """Domain and visibility values from chunks are preserved in migration."""
        db_path = tmp_path / "memory.sqlite"
        self._seed_old_schema(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at, domain, visibility) "
            "VALUES ('Private work note', '/vault/work.md', '2026-01-01', 'work', 'private')"
        )
        conn.execute(
            "INSERT INTO chunks (content, file_path, created_at, domain, visibility) "
            "VALUES ('Shared note', '/vault/shared.md', '2026-01-02', 'shared', 'shared')"
        )
        conn.commit()
        conn.close()

        from scripts.migrate_memory_schema import migrate

        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT content, domain, visibility FROM memories ORDER BY created_at").fetchall()
        assert rows[0] == ("Private work note", "work", "private")
        assert rows[1] == ("Shared note", "shared", "shared")
        conn.close()
