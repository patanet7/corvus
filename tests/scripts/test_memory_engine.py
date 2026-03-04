"""Tests for the hybrid memory search engine."""

import sqlite3

import pytest

from scripts.common.memory_engine import (
    MemoryEngine,
    SearchResult,
    init_db,
)


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with test data."""
    db_file = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_file))
    init_db(conn)

    # Insert test chunks
    test_data = [
        ("Thomas prefers dark mode and uses Vim keybindings.", "memory/personal.md", 0, "2026-02-20"),
        ("Homelab has 4 hosts: laptop-server, miniserver, optiplex, NAS.", "memory/projects.md", 0, "2026-02-22"),
        ("Meeting with Dr. Smith about medication review on Tuesday.", "memory/health.md", 0, "2026-02-25"),
        ("Practiced Chopin Ballade No. 1 — worked on the coda section.", "memory/2026-02-25.md", 0, "2026-02-25"),
        ("Set up Grafana dashboards for fleet monitoring.", "memory/2026-02-24.md", 0, "2026-02-24"),
    ]
    for content, file_path, chunk_idx, created_at in test_data:
        conn.execute(
            "INSERT INTO chunks (content, file_path, chunk_index, created_at) VALUES (?, ?, ?, ?)",
            (content, file_path, chunk_idx, created_at),
        )
    conn.commit()

    # Rebuild FTS index
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    return db_file


def test_bm25_search_returns_results(db_path):
    engine = MemoryEngine(db_path, cognee_enabled=False)
    results = engine.search("homelab hosts")
    assert len(results) > 0
    assert any("homelab" in r.content.lower() for r in results)


def test_bm25_search_respects_limit(db_path):
    engine = MemoryEngine(db_path, cognee_enabled=False)
    results = engine.search("memory", limit=2)
    assert len(results) <= 2


def test_bm25_search_no_results(db_path):
    engine = MemoryEngine(db_path, cognee_enabled=False)
    results = engine.search("xyznonexistentterm")
    assert len(results) == 0


def test_search_result_has_required_fields(db_path):
    engine = MemoryEngine(db_path, cognee_enabled=False)
    results = engine.search("Chopin")
    assert len(results) > 0
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.content
    assert r.file_path
    assert r.score is not None
    assert r.created_at
