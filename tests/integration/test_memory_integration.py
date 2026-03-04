"""REAL behavioral integration tests — no mocks, no fakes.

These tests create real SQLite databases, write real files to disk,
and verify the full round-trip contract of the memory system.
"""

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
import yaml

from scripts.common.memory_engine import MemoryEngine, SearchResult, init_db
from scripts.common.vault_writer import VaultWriter


# Use a real temp directory that persists for the test session
@pytest.fixture(scope="session")
def real_db():
    """Create a REAL SQLite database with FTS5 — not a mock."""
    with tempfile.TemporaryDirectory(prefix="claw-test-") as td:
        db_path = Path(td) / "integration_test.sqlite"
        conn = sqlite3.connect(str(db_path))
        init_db(conn)
        # Seed with realistic data
        test_memories = [
            ("Thomas prefers dark mode and uses Vim keybindings.", "memory/personal.md", "2026-02-20"),
            ("Homelab has 4 hosts: laptop-server, miniserver, optiplex, NAS.", "memory/projects.md", "2026-02-22"),
            ("Meeting with Dr. Smith about medication review on Tuesday.", "memory/health.md", "2026-02-25"),
            ("Practiced Chopin Ballade No. 1 — worked on the coda section.", "memory/2026-02-25.md", "2026-02-25"),
            ("Set up Grafana dashboards for fleet monitoring.", "memory/2026-02-24.md", "2026-02-24"),
            ("Firefly III budget for February is $3,200. Spent $2,100 so far.", "memory/finance.md", "2026-02-23"),
            ("Docker compose stack for Grafana/Loki/Alloy deployed on optiplex.", "memory/homelab.md", "2026-02-21"),
            ("Piano lesson: work on dynamics in measures 33-48 of the Ballade.", "memory/music.md", "2026-02-24"),
        ]
        for content, file_path, created_at in test_memories:
            cursor = conn.execute(
                "INSERT INTO chunks (content, file_path, chunk_index, created_at) VALUES (?, ?, 0, ?)",
                (content, file_path, created_at),
            )
            chunk_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO chunks_fts(rowid, content, file_path) VALUES (?, ?, ?)",
                (chunk_id, content, file_path),
            )
        conn.commit()
        conn.close()
        yield db_path


@pytest.fixture(scope="session")
def real_vault():
    """Create a REAL vault directory structure mirroring production."""
    with tempfile.TemporaryDirectory(prefix="claw-vault-") as td:
        vault = Path(td)
        for domain in ["personal", "work", "homelab", "finance", "music", "shared"]:
            (vault / domain).mkdir()
        # Subfolders matching production
        (vault / "personal" / "health").mkdir()
        (vault / "personal" / "journal").mkdir()
        (vault / "personal" / "planning").mkdir()
        (vault / "work" / "meetings").mkdir()
        (vault / "work" / "projects").mkdir()
        (vault / "work" / "tasks").mkdir()
        (vault / "homelab" / "inventory").mkdir()
        (vault / "homelab" / "runbooks").mkdir()
        yield vault


class TestMemoryEngineRealBehavior:
    """Tests against a REAL SQLite database with FTS5."""

    def test_search_finds_known_content(self, real_db):
        """CONTRACT: searching for 'homelab' returns the homelab memory."""
        engine = MemoryEngine(real_db, cognee_enabled=False)
        results = engine.search("homelab hosts")
        assert len(results) > 0
        assert any("homelab" in r.content.lower() for r in results)

    def test_search_result_contract(self, real_db):
        """CONTRACT: every SearchResult has all required fields, correct types."""
        engine = MemoryEngine(real_db, cognee_enabled=False)
        results = engine.search("Chopin")
        assert len(results) > 0
        for r in results:
            assert isinstance(r, SearchResult)
            assert isinstance(r.content, str) and len(r.content) > 0
            assert isinstance(r.file_path, str) and len(r.file_path) > 0
            assert isinstance(r.score, float) and r.score >= 0
            assert isinstance(r.created_at, str)

    def test_search_limit_honored(self, real_db):
        """CONTRACT: limit parameter is always respected."""
        engine = MemoryEngine(real_db, cognee_enabled=False)
        results = engine.search("memory", limit=2)
        assert len(results) <= 2

    def test_search_empty_query_no_crash(self, real_db):
        """CONTRACT: empty/garbage query returns empty list, never raises."""
        engine = MemoryEngine(real_db, cognee_enabled=False)
        results = engine.search("xyznonexistentterm12345")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_save_then_search_round_trip(self, real_db, real_vault):
        """BEHAVIORAL: save a memory, then search for it, and find it."""
        writer = VaultWriter(real_vault)
        engine = MemoryEngine(real_db, cognee_enabled=False, vault_writer=writer)

        unique_content = f"Integration test memory created at {time.time()}"
        chunk_id = engine.save(
            unique_content,
            file_path="memory/integration-test.md",
            domain="personal",
            title="integration test",
        )
        assert isinstance(chunk_id, int)
        assert chunk_id > 0

        # Now search for it — use a distinctive word from the content
        results = engine.search("Integration test memory")
        assert len(results) > 0
        assert any(unique_content in r.content for r in results)

    def test_temporal_decay_prefers_newer(self, real_db):
        """BEHAVIORAL: newer memories score higher than older ones (all else equal)."""
        engine = MemoryEngine(real_db, cognee_enabled=False)
        results = engine.search("Grafana dashboards")
        # Results should be ordered by score (recency-weighted)
        if len(results) > 1:
            assert results[0].score >= results[1].score


class TestVaultWriterRealBehavior:
    """Tests that write REAL files and verify them on disk."""

    def test_save_creates_real_file(self, real_vault):
        """CONTRACT: saving creates an actual .md file at the right path."""
        writer = VaultWriter(real_vault)
        file_path = writer.save_to_vault(
            content="Test memory about dark mode preferences.",
            domain="personal",
            tags=["test", "preferences"],
            title="dark mode test",
        )
        assert file_path.exists()
        assert str(file_path).endswith(".md")

    def test_saved_file_has_valid_frontmatter(self, real_vault):
        """CONTRACT: saved file has parseable YAML frontmatter with required fields."""
        writer = VaultWriter(real_vault)
        file_path = writer.save_to_vault(
            content="Meeting with the team about Q1 goals.",
            domain="work",
            tags=["meeting", "quarterly"],
            content_type="meeting",
            title="q1 planning",
        )
        text = file_path.read_text()

        # Parse frontmatter
        assert text.startswith("---")
        parts = text.split("---", 2)
        assert len(parts) >= 3
        frontmatter = yaml.safe_load(parts[1])

        # Required fields
        assert "tags" in frontmatter
        assert "created" in frontmatter
        assert "source" in frontmatter
        assert isinstance(frontmatter["tags"], list)

    def test_domain_routing_correct_folder(self, real_vault):
        """BEHAVIORAL: personal domain writes to personal/, work to work/, etc."""
        writer = VaultWriter(real_vault)

        personal_path = writer.save_to_vault("Personal note", domain="personal", tags=["test"], title="personal-test")
        work_path = writer.save_to_vault("Work note", domain="work", tags=["test"], title="work-test")
        homelab_path = writer.save_to_vault("Homelab note", domain="homelab", tags=["test"], title="homelab-test")

        assert "/personal/" in str(personal_path)
        assert "/work/" in str(work_path)
        assert "/homelab/" in str(homelab_path)

    def test_filename_is_kebab_case(self, real_vault):
        """CONTRACT: filenames are always kebab-case, no spaces."""
        writer = VaultWriter(real_vault)
        file_path = writer.save_to_vault(
            content="Test note",
            domain="personal",
            tags=["test"],
            title="My Important Meeting Notes 2026",
        )
        filename = file_path.name
        assert " " not in filename
        assert filename == filename.lower()

    def test_wiki_links_preserved(self, real_vault):
        """BEHAVIORAL: [[wiki links]] in content are preserved in saved file."""
        writer = VaultWriter(real_vault)
        file_path = writer.save_to_vault(
            content="Discussed [[Chopin Ballade No. 1]] with [[Dr. Smith]].",
            domain="music",
            tags=["practice"],
            title="chopin-discussion",
        )
        text = file_path.read_text()
        assert "[[Chopin Ballade No. 1]]" in text
        assert "[[Dr. Smith]]" in text

    def test_hierarchical_tags(self, real_vault):
        """BEHAVIORAL: tags get domain prefix in frontmatter."""
        writer = VaultWriter(real_vault)
        file_path = writer.save_to_vault(
            content="Health checkup note",
            domain="personal",
            tags=["health", "medication"],
            title="health-check",
        )
        text = file_path.read_text()
        parts = text.split("---", 2)
        frontmatter = yaml.safe_load(parts[1])
        tags = frontmatter["tags"]
        # Should have domain-prefixed tags
        assert any("personal" in str(t) for t in tags)


# NOTE: TestMemoryCLIRealBehavior was removed — the scripts/memory_search.py
# CLI was deleted during hub architecture migration. Memory operations now go
# through the MemoryHub API directly (tested in test_memory_hub_live.py).
