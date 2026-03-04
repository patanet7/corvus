"""Tests for the Obsidian vault writer — frontmatter, links, routing, naming."""

import sqlite3
from datetime import UTC, datetime

import pytest
import yaml

from scripts.common.memory_engine import MemoryEngine, init_db
from scripts.common.vault_writer import (
    VaultWriter,
    _build_hierarchical_tags,
    generate_frontmatter,
    resolve_links,
    route_to_folder,
    slugify,
)

# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic_title(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("Dr. Smith's Notes!") == "dr-smith-s-notes"

    def test_accented_characters(self):
        assert slugify("Résumé café") == "resume-cafe"

    def test_consecutive_hyphens_collapsed(self):
        assert slugify("foo---bar") == "foo-bar"

    def test_leading_trailing_hyphens_stripped(self):
        assert slugify("--hello--") == "hello"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_numbers_preserved(self):
        assert slugify("Chopin Ballade No 1") == "chopin-ballade-no-1"

    def test_no_spaces_in_output(self):
        result = slugify("Meeting with Dr. Smith on 2026-02-26")
        assert " " not in result


# ---------------------------------------------------------------------------
# generate_frontmatter
# ---------------------------------------------------------------------------


class TestGenerateFrontmatter:
    def test_valid_yaml(self):
        fm = generate_frontmatter(
            tags=["memory", "health"],
            source="claw-personal-agent",
        )
        # Strip YAML delimiters and parse
        inner = fm.replace("---", "").strip()
        parsed = yaml.safe_load(inner)
        assert parsed["tags"] == ["memory", "health"]
        assert parsed["source"] == "claw-personal-agent"
        assert "created" in parsed
        assert parsed["importance"] == 0.5

    def test_always_has_tags_created_source(self):
        fm = generate_frontmatter(tags=[], source="test")
        assert "tags:" in fm
        assert "created:" in fm
        assert "source:" in fm

    def test_aliases_included_when_provided(self):
        fm = generate_frontmatter(
            tags=["test"],
            source="test",
            aliases=["alias1", "alias2"],
        )
        assert "aliases:" in fm
        assert "alias1" in fm

    def test_aliases_absent_when_not_provided(self):
        fm = generate_frontmatter(tags=["test"], source="test")
        assert "aliases:" not in fm

    def test_custom_importance(self):
        fm = generate_frontmatter(tags=[], source="test", importance=0.9)
        assert "importance: 0.9" in fm

    def test_custom_created_datetime(self):
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        fm = generate_frontmatter(tags=[], source="test", created=dt)
        assert "2026-01-15T10:30:00Z" in fm


# ---------------------------------------------------------------------------
# resolve_links
# ---------------------------------------------------------------------------


class TestResolveLinks:
    def test_bare_date_gets_linked(self):
        result = resolve_links("Meeting on 2026-02-26 was good.")
        assert "[[2026-02-26]]" in result

    def test_existing_wiki_links_preserved(self):
        result = resolve_links("See [[Dr. Smith]] for details.")
        assert "[[Dr. Smith]]" in result

    def test_already_linked_date_not_double_wrapped(self):
        result = resolve_links("See [[2026-02-26]] daily note.")
        # Should not become [[[[2026-02-26]]]]
        assert result.count("[[2026-02-26]]") == 1
        assert "[[[[" not in result

    def test_multiple_dates_linked(self):
        result = resolve_links("From 2026-01-01 to 2026-12-31.")
        assert "[[2026-01-01]]" in result
        assert "[[2026-12-31]]" in result


# ---------------------------------------------------------------------------
# route_to_folder
# ---------------------------------------------------------------------------


class TestRouteToFolder:
    def test_personal_domain(self, tmp_path):
        result = route_to_folder(tmp_path, "personal")
        assert result == tmp_path / "personal"

    def test_homelab_domain(self, tmp_path):
        result = route_to_folder(tmp_path, "homelab")
        assert result == tmp_path / "homelab"

    def test_unknown_domain_goes_to_shared(self, tmp_path):
        result = route_to_folder(tmp_path, "unknown_domain")
        assert result == tmp_path / "shared"

    def test_content_type_subfolder(self, tmp_path):
        result = route_to_folder(tmp_path, "personal", "journal")
        assert result == tmp_path / "personal" / "journal"

    def test_meeting_content_type(self, tmp_path):
        result = route_to_folder(tmp_path, "work", "meeting")
        assert result == tmp_path / "work" / "meetings"

    def test_unknown_content_type_ignored(self, tmp_path):
        result = route_to_folder(tmp_path, "personal", "weird_type")
        assert result == tmp_path / "personal"


# ---------------------------------------------------------------------------
# _build_hierarchical_tags
# ---------------------------------------------------------------------------


class TestBuildHierarchicalTags:
    def test_adds_domain_prefix(self):
        tags = _build_hierarchical_tags(["health", "medication"], "personal")
        assert "personal" in tags

    def test_domain_tag_not_duplicated(self):
        tags = _build_hierarchical_tags(["personal", "health"], "personal")
        assert tags.count("personal") == 1

    def test_hierarchical_domain_tag_detected(self):
        tags = _build_hierarchical_tags(["homelab/docker"], "homelab")
        # Should not add bare "homelab" since "homelab/docker" is present
        assert "homelab" not in [t for t in tags if "/" not in t] or any(t.startswith("homelab/") for t in tags)

    def test_hash_prefix_stripped(self):
        tags = _build_hierarchical_tags(["#health", "#medication"], "personal")
        assert all(not t.startswith("#") for t in tags)

    def test_empty_tags_gets_domain(self):
        tags = _build_hierarchical_tags([], "music")
        assert tags == ["music"]


# ---------------------------------------------------------------------------
# VaultWriter — integration
# ---------------------------------------------------------------------------


class TestVaultWriter:
    @pytest.fixture
    def vault(self, tmp_path):
        return VaultWriter(tmp_path)

    def test_save_creates_file(self, vault, tmp_path):
        path = vault.save_to_vault(
            content="Test memory content.",
            domain="personal",
            tags=["test"],
        )
        assert path.exists()
        assert path.suffix == ".md"

    def test_file_has_valid_frontmatter(self, vault, tmp_path):
        path = vault.save_to_vault(
            content="Test content.",
            domain="personal",
            tags=["health", "medication"],
            source="claw-personal-agent",
            importance=0.7,
        )
        text = path.read_text()
        # Extract frontmatter between --- delimiters
        parts = text.split("---")
        assert len(parts) >= 3, "File must have YAML frontmatter delimiters"
        fm_text = parts[1].strip()
        parsed = yaml.safe_load(fm_text)
        assert "created" in parsed
        assert "source" in parsed
        assert "tags" in parsed

    def test_frontmatter_always_has_tags_created_source(self, vault):
        path = vault.save_to_vault(content="Bare.", domain="work")
        text = path.read_text()
        assert "tags:" in text
        assert "created:" in text
        assert "source:" in text

    def test_file_lands_in_correct_domain_folder(self, vault, tmp_path):
        path = vault.save_to_vault(content="Homelab note.", domain="homelab")
        assert tmp_path / "homelab" in path.parents or path.parent == tmp_path / "homelab"

    def test_personal_domain_writes_to_personal(self, vault, tmp_path):
        path = vault.save_to_vault(content="Personal.", domain="personal")
        assert "personal" in str(path)

    def test_filename_is_kebab_case(self, vault):
        path = vault.save_to_vault(
            content="Test.",
            domain="work",
            title="My Important Meeting Notes",
        )
        filename = path.stem
        assert " " not in filename
        assert filename == filename.lower()

    def test_wiki_links_preserved(self, vault):
        path = vault.save_to_vault(
            content="Discussed [[Chopin Ballade No. 1]] practice strategy.",
            domain="music",
        )
        text = path.read_text()
        assert "[[Chopin Ballade No. 1]]" in text

    def test_hierarchical_tags_in_frontmatter(self, vault):
        path = vault.save_to_vault(
            content="Docker issue.",
            domain="homelab",
            tags=["homelab/docker", "troubleshooting"],
        )
        text = path.read_text()
        assert "homelab/docker" in text

    def test_journal_content_type_naming(self, vault):
        dt = datetime(2026, 2, 26, 12, 0, 0, tzinfo=UTC)
        path = vault.save_to_vault(
            content="Today's journal entry.",
            domain="personal",
            content_type="journal",
            created=dt,
        )
        assert path.name == "2026-02-26.md"
        assert "journal" in str(path.parent)

    def test_journal_appends_to_existing_daily_note(self, vault):
        dt = datetime(2026, 2, 26, 10, 0, 0, tzinfo=UTC)
        # First entry creates file
        path = vault.save_to_vault(
            content="Morning entry.",
            domain="personal",
            content_type="journal",
            created=dt,
        )
        # Second entry appends
        dt2 = datetime(2026, 2, 26, 15, 30, 0, tzinfo=UTC)
        path2 = vault.save_to_vault(
            content="Afternoon entry.",
            domain="personal",
            content_type="journal",
            created=dt2,
        )
        assert path == path2  # Same file
        text = path.read_text()
        assert "Morning entry." in text
        assert "Afternoon entry." in text
        assert "15:30" in text  # Time header for appended entry

    def test_meeting_content_type_naming(self, vault):
        dt = datetime(2026, 2, 26, 14, 0, 0, tzinfo=UTC)
        path = vault.save_to_vault(
            content="Discussed roadmap.",
            domain="work",
            content_type="meeting",
            title="Q1 Planning Review",
            created=dt,
        )
        assert path.name == "2026-02-26-q1-planning-review.md"
        assert "meetings" in str(path.parent)

    def test_auto_links_dates(self, vault):
        path = vault.save_to_vault(
            content="Follow up on 2026-03-01 about the project.",
            domain="work",
        )
        text = path.read_text()
        assert "[[2026-03-01]]" in text

    def test_aliases_written(self, vault):
        path = vault.save_to_vault(
            content="Med review.",
            domain="personal",
            aliases=["med review", "doctor appointment"],
        )
        text = path.read_text()
        assert "aliases:" in text
        assert "med review" in text

    def test_importance_written(self, vault):
        path = vault.save_to_vault(content="Critical.", domain="personal", importance=0.9)
        text = path.read_text()
        assert "importance: 0.9" in text

    def test_source_defaults_to_domain_agent(self, vault):
        path = vault.save_to_vault(content="Test.", domain="finance")
        text = path.read_text()
        assert "source: claw-finance-agent" in text

    def test_folder_created_if_missing(self, vault, tmp_path):
        # music/practice doesn't exist yet
        path = vault.save_to_vault(
            content="Practice log.",
            domain="music",
        )
        assert path.exists()


# ---------------------------------------------------------------------------
# MemoryEngine + VaultWriter integration
# ---------------------------------------------------------------------------


class TestMemoryEngineVaultIntegration:
    @pytest.fixture
    def engine_with_vault(self, tmp_path):
        db_file = tmp_path / "test.sqlite"
        conn = sqlite3.connect(str(db_file))
        init_db(conn)
        conn.close()

        vault_root = tmp_path / "vaults"
        vault_root.mkdir()
        writer = VaultWriter(vault_root)
        return MemoryEngine(db_file, vault_writer=writer), vault_root

    def test_save_with_vault_writes_file_and_indexes(self, engine_with_vault):
        engine, vault_root = engine_with_vault
        chunk_id = engine.save(
            content="Practiced scales today.",
            file_path="memory/music.md",
            domain="music",
            tags=["practice"],
            title="scales-practice",
        )
        assert chunk_id > 0

        # Verify vault file exists
        music_files = list((vault_root / "music").rglob("*.md"))
        assert len(music_files) == 1
        text = music_files[0].read_text()
        assert "Practiced scales today." in text
        assert "tags:" in text

        # Verify SQLite has the entry pointing to vault path
        results = engine.search("scales")
        assert len(results) > 0
        assert "music" in results[0].file_path

    def test_save_without_domain_skips_vault(self, engine_with_vault):
        engine, vault_root = engine_with_vault
        chunk_id = engine.save(
            content="No domain note.",
            file_path="memory/misc.md",
        )
        assert chunk_id > 0
        # No vault files should be created
        all_md = list(vault_root.rglob("*.md"))
        assert len(all_md) == 0

    def test_save_without_vault_writer_works(self, tmp_path):
        db_file = tmp_path / "test.sqlite"
        conn = sqlite3.connect(str(db_file))
        init_db(conn)
        conn.close()

        engine = MemoryEngine(db_file)
        chunk_id = engine.save(
            content="Plain save.",
            file_path="memory/test.md",
            domain="personal",
        )
        assert chunk_id > 0
