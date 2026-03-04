"""Behavioral tests for the background re-indexer.

Real temp dirs, real markdown files, real SQLite — NO mocks.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts.reindex import (
    chunk_markdown,
    estimate_tokens,
    file_hash,
    infer_domain,
    reindex,
    strip_frontmatter,
)


class TestEstimateTokens:
    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_sentence(self) -> None:
        tokens = estimate_tokens("Hello world this is a test")
        assert tokens > 0
        # 6 words * 1.3 ~= 7-8
        assert 7 <= tokens <= 8


class TestFileHash:
    def test_consistent_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("Hello world")
        h1 = file_hash(f)
        h2 = file_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text("Hello")
        f2.write_text("World")
        assert file_hash(f1) != file_hash(f2)


class TestStripFrontmatter:
    def test_no_frontmatter(self) -> None:
        body, meta = strip_frontmatter("# Just a heading\n\nContent here.")
        assert body == "# Just a heading\n\nContent here."
        assert meta == {}

    def test_with_frontmatter(self) -> None:
        text = "---\ntags: test\ndomain: personal\n---\n\n# Heading\n\nBody text."
        body, meta = strip_frontmatter(text)
        assert "# Heading" in body
        assert "Body text." in body
        assert meta["tags"] == "test"
        assert meta["domain"] == "personal"

    def test_frontmatter_no_closing(self) -> None:
        text = "---\ntags: test\nThis has no closing delimiter"
        body, meta = strip_frontmatter(text)
        # Should return original text since frontmatter is malformed
        assert body == text
        assert meta == {}


class TestChunkMarkdown:
    def test_empty_content(self) -> None:
        assert chunk_markdown("") == []

    def test_frontmatter_only(self) -> None:
        assert chunk_markdown("---\ntags: []\n---\n") == []

    def test_splits_at_h2_headings(self) -> None:
        text = "---\ntags: []\n---\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        chunks = chunk_markdown(text)
        assert len(chunks) == 2
        assert "Content A" in chunks[0]
        assert "Content B" in chunks[1]

    def test_single_section_no_split(self) -> None:
        text = "## Only Section\n\nShort content here."
        chunks = chunk_markdown(text)
        assert len(chunks) == 1

    def test_preserves_heading_text(self) -> None:
        text = "## Important Section\n\nDetails about the section."
        chunks = chunk_markdown(text)
        assert any("Important Section" in c for c in chunks)


class TestInferDomain:
    def test_known_domain(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "personal").mkdir(parents=True)
        f = vault / "personal" / "note.md"
        f.write_text("test")
        assert infer_domain(f, vault) == "personal"

    def test_unknown_domain(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "random").mkdir(parents=True)
        f = vault / "random" / "note.md"
        f.write_text("test")
        assert infer_domain(f, vault) is None

    def test_root_level_file(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        f = vault / "note.md"
        f.write_text("test")
        assert infer_domain(f, vault) is None


class TestReindex:
    def test_new_files(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "personal").mkdir(parents=True)
        (vault / "personal" / "note-one.md").write_text(
            "---\ntags: [test]\n---\n\n## Section One\n\nSome content here.\n\n## Section Two\n\nMore content."
        )
        db = tmp_path / "test.sqlite"

        stats = reindex(vault_dir=vault, db_path=db, cognee_enabled=False)
        assert stats["scanned"] == 1
        assert stats["new"] == 1
        assert stats["chunks_created"] > 0
        assert stats["errors"] == []

    def test_unchanged_files_skip(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("# Test\n\nContent here.")
        db = tmp_path / "test.sqlite"

        stats1 = reindex(vault_dir=vault, db_path=db, cognee_enabled=False)
        assert stats1["new"] == 1

        stats2 = reindex(vault_dir=vault, db_path=db, cognee_enabled=False)
        assert stats2["unchanged"] == 1
        assert stats2["new"] == 0

    def test_detects_modified_file(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        note = vault / "note.md"
        note.write_text("# Original\n\nOriginal content.")
        db = tmp_path / "test.sqlite"

        reindex(vault_dir=vault, db_path=db, cognee_enabled=False)
        note.write_text("# Updated\n\nNew content added.")
        stats = reindex(vault_dir=vault, db_path=db, cognee_enabled=False)
        assert stats["updated"] == 1

    def test_dry_run_no_changes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("# Test\n\nContent.")
        db = tmp_path / "test.sqlite"

        stats = reindex(vault_dir=vault, db_path=db, dry_run=True, cognee_enabled=False)
        assert stats["new"] == 1
        assert stats["chunks_created"] == 0

    def test_force_reindexes_unchanged(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("# Test\n\nContent.")
        db = tmp_path / "test.sqlite"

        reindex(vault_dir=vault, db_path=db, cognee_enabled=False)
        stats = reindex(vault_dir=vault, db_path=db, force=True, cognee_enabled=False)
        assert stats["updated"] == 1
        assert stats["unchanged"] == 0

    def test_domain_filter(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "personal").mkdir(parents=True)
        (vault / "work").mkdir(parents=True)
        (vault / "personal" / "note.md").write_text("# Personal\n\nContent.")
        (vault / "work" / "note.md").write_text("# Work\n\nContent.")
        db = tmp_path / "test.sqlite"

        stats = reindex(vault_dir=vault, db_path=db, domain_filter="personal", cognee_enabled=False)
        assert stats["scanned"] == 1
        assert stats["new"] == 1

    def test_fts5_searchable_after_index(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("# Unique\n\nSupercalifragilistic content.")
        db = tmp_path / "test.sqlite"

        reindex(vault_dir=vault, db_path=db, cognee_enabled=False)

        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT content FROM chunks_fts WHERE chunks_fts MATCH ?",
            ("Supercalifragilistic",),
        ).fetchall()
        conn.close()
        assert len(rows) > 0

    def test_cli_json_output(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("# CLI Test\n\nContent.")
        db = tmp_path / "test.sqlite"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.reindex",
                "--vault-dir",
                str(vault),
                "--db",
                str(db),
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "scanned" in output
        assert "new" in output
        assert "chunks_created" in output
