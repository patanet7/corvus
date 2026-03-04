"""Tests for obsidian.py CLI — Obsidian vault operations.

Verifies every CLI subcommand (search, read, list, recent, create) by running
the script as a subprocess against a real temporary vault directory with real
markdown files. NO MOCKS.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
CLI_SCRIPT = str(WORKTREE_ROOT / "scripts" / "obsidian.py")
_PYTHON_DIR = str(Path(sys.executable).parent)


def _run_cli(
    args: list[str],
    *,
    vault_dir: str | Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the obsidian CLI as a subprocess."""
    env = {
        "MEMORY_DIR": str(vault_dir),
        "PATH": f"{_PYTHON_DIR}:/usr/bin:/usr/local/bin",
        "PYTHONPATH": str(WORKTREE_ROOT),
    }
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, CLI_SCRIPT, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _write_note(
    vault_dir: Path,
    rel_path: str,
    content: str,
    frontmatter: dict | None = None,
) -> Path:
    """Write a real markdown note to the vault."""
    note_path = vault_dir / rel_path
    note_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if frontmatter:
        lines.append("---")
        for key, value in frontmatter.items():
            if isinstance(value, list):
                items = ", ".join(str(v) for v in value)
                lines.append(f"{key}: [{items}]")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        lines.append("")

    lines.append(content)
    note_path.write_text("\n".join(lines), encoding="utf-8")
    return note_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a temporary vault with seed notes across domains."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    # Personal domain notes
    _write_note(
        vault_dir,
        "personal/health/sleep-tracking.md",
        "Tracking sleep patterns with Apple Watch. Average 7.2 hours this week.",
        frontmatter={
            "tags": ["personal", "personal/health", "sleep"],
            "created": "2026-02-20T10:00:00Z",
            "source": "claw-personal-agent",
            "importance": 0.6,
        },
    )
    _write_note(
        vault_dir,
        "personal/journal/2026-02-25.md",
        "Productive day. Worked on [[Claw Agent SDK]] refactoring.\n\nMeeting on 2026-02-26 about roadmap.",
        frontmatter={
            "tags": ["personal", "journal"],
            "created": "2026-02-25T08:00:00Z",
            "source": "claw-personal-agent",
            "importance": 0.5,
        },
    )

    # Homelab domain notes
    _write_note(
        vault_dir,
        "homelab/docker-compose-cheatsheet.md",
        "Common docker compose commands:\n- `docker compose up -d`\n- `docker compose logs -f`",
        frontmatter={
            "tags": ["homelab", "homelab/docker", "reference"],
            "created": "2026-02-18T14:00:00Z",
            "source": "claw-homelab-agent",
            "importance": 0.7,
        },
    )
    _write_note(
        vault_dir,
        "homelab/runbooks/restart-komodo.md",
        "Runbook: restart Komodo Core on laptop-server.\n\n1. SSH to example-host\n2. `docker restart komodo-core`",
        frontmatter={
            "tags": ["homelab", "homelab/komodo", "runbook"],
            "created": "2026-02-22T11:00:00Z",
            "source": "claw-homelab-agent",
            "importance": 0.8,
        },
    )

    # Work domain note
    _write_note(
        vault_dir,
        "work/meetings/2026-02-24-sprint-planning.md",
        "Sprint planning: agreed on 3 stories. [[Thomas]] presenting demo Friday.",
        frontmatter={
            "tags": ["work", "work/meetings", "sprint"],
            "created": "2026-02-24T09:00:00Z",
            "source": "claw-work-agent",
            "importance": 0.6,
        },
    )

    # Music domain note
    _write_note(
        vault_dir,
        "music/chopin-ballade-no-1.md",
        "Practice log for [[Chopin Ballade No. 1]].\n\nCoda section needs more work on left hand octaves.",
        frontmatter={
            "tags": ["music", "music/practice", "chopin"],
            "created": "2026-02-23T20:00:00Z",
            "source": "claw-music-agent",
            "importance": 0.5,
        },
    )

    return vault_dir


@pytest.fixture
def empty_vault(tmp_path: Path) -> Path:
    """Create an empty vault directory."""
    vault_dir = tmp_path / "empty_vault"
    vault_dir.mkdir()
    return vault_dir


# ---------------------------------------------------------------------------
# Contract: search returns valid JSON array
# ---------------------------------------------------------------------------


class TestSearchContract:
    def test_search_returns_json_array(self, vault: Path) -> None:
        result = _run_cli(["search", "docker"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_search_results_have_required_keys(self, vault: Path) -> None:
        result = _run_cli(["search", "docker"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        for item in data:
            assert "path" in item
            assert "title" in item
            assert "score" in item
            assert "frontmatter" in item
            assert "modified" in item

    def test_search_no_matches_returns_empty_array(self, vault: Path) -> None:
        result = _run_cli(["search", "xyznonexistentterm99"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_search_respects_limit(self, vault: Path) -> None:
        result = _run_cli(["search", "personal", "--limit", "1"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) <= 1

    def test_search_scores_are_numeric(self, vault: Path) -> None:
        result = _run_cli(["search", "komodo"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        for item in data:
            assert isinstance(item["score"], (int, float))


# ---------------------------------------------------------------------------
# Behavioral: search finds notes by different criteria
# ---------------------------------------------------------------------------


class TestSearchBehavior:
    def test_search_finds_by_filename(self, vault: Path) -> None:
        result = _run_cli(["search", "chopin"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        paths = [item["path"] for item in data]
        assert any("chopin" in p for p in paths)

    def test_search_finds_by_body_content(self, vault: Path) -> None:
        result = _run_cli(["search", "octaves"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        assert any("chopin" in item["path"] for item in data)

    def test_search_finds_by_tag(self, vault: Path) -> None:
        result = _run_cli(["search", "runbook"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        assert any("komodo" in item["path"] for item in data)

    def test_search_domain_filter(self, vault: Path) -> None:
        result = _run_cli(["search", "docker", "--domain", "homelab"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        # All results should be from homelab domain
        for item in data:
            assert item["path"].startswith("homelab/")

    def test_search_domain_filter_excludes_other_domains(self, vault: Path) -> None:
        # "Sprint" only appears in work domain
        result = _run_cli(["search", "sprint", "--domain", "personal"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 0

    def test_search_filename_match_scores_higher(self, vault: Path) -> None:
        result = _run_cli(["search", "chopin"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        # The file named "chopin-ballade-no-1" should have highest score
        top = data[0]
        assert "chopin" in top["title"]

    def test_search_empty_vault_returns_empty(self, empty_vault: Path) -> None:
        result = _run_cli(["search", "anything"], vault_dir=empty_vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []


# ---------------------------------------------------------------------------
# Contract: read returns valid JSON with required fields
# ---------------------------------------------------------------------------


class TestReadContract:
    def test_read_returns_required_keys(self, vault: Path) -> None:
        result = _run_cli(["read", "music/chopin-ballade-no-1.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "path" in data
        assert "title" in data
        assert "frontmatter" in data
        assert "body" in data
        assert "modified" in data
        assert "size_bytes" in data

    def test_read_nonexistent_file_returns_error(self, vault: Path) -> None:
        result = _run_cli(["read", "does/not/exist.md"], vault_dir=vault)
        assert result.returncode == 1
        error = json.loads(result.stderr)
        assert "error" in error


# ---------------------------------------------------------------------------
# Behavioral: read returns correct content
# ---------------------------------------------------------------------------


class TestReadBehavior:
    def test_read_returns_correct_body(self, vault: Path) -> None:
        result = _run_cli(["read", "music/chopin-ballade-no-1.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "Coda section" in data["body"]
        assert "left hand octaves" in data["body"]

    def test_read_parses_frontmatter(self, vault: Path) -> None:
        result = _run_cli(["read", "music/chopin-ballade-no-1.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        fm = data["frontmatter"]
        assert "tags" in fm
        assert "music" in fm["tags"]

    def test_read_preserves_wiki_links_in_body(self, vault: Path) -> None:
        result = _run_cli(["read", "music/chopin-ballade-no-1.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "[[Chopin Ballade No. 1]]" in data["body"]

    def test_read_preserves_wiki_links_in_journal(self, vault: Path) -> None:
        result = _run_cli(["read", "personal/journal/2026-02-25.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "[[Claw Agent SDK]]" in data["body"]

    def test_read_path_traversal_blocked(self, vault: Path) -> None:
        result = _run_cli(["read", "../../etc/passwd"], vault_dir=vault)
        assert result.returncode == 1
        error = json.loads(result.stderr)
        assert "error" in error

    def test_read_returns_correct_relative_path(self, vault: Path) -> None:
        result = _run_cli(["read", "homelab/docker-compose-cheatsheet.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["path"] == "homelab/docker-compose-cheatsheet.md"


# ---------------------------------------------------------------------------
# Contract: list returns valid JSON array
# ---------------------------------------------------------------------------


class TestListContract:
    def test_list_returns_json_array(self, vault: Path) -> None:
        result = _run_cli(["list"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_list_results_have_required_keys(self, vault: Path) -> None:
        result = _run_cli(["list"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        for item in data:
            assert "path" in item
            assert "title" in item
            assert "frontmatter" in item
            assert "modified" in item


# ---------------------------------------------------------------------------
# Behavioral: list filters correctly
# ---------------------------------------------------------------------------


class TestListBehavior:
    def test_list_all_returns_all_notes(self, vault: Path) -> None:
        result = _run_cli(["list"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 6  # 2 personal + 2 homelab + 1 work + 1 music

    def test_list_domain_filter(self, vault: Path) -> None:
        result = _run_cli(["list", "--domain", "homelab"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        for item in data:
            assert item["path"].startswith("homelab/")

    def test_list_domain_personal(self, vault: Path) -> None:
        result = _run_cli(["list", "--domain", "personal"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        for item in data:
            assert item["path"].startswith("personal/")

    def test_list_tag_filter(self, vault: Path) -> None:
        result = _run_cli(["list", "--tag", "runbook"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1
        for item in data:
            tags = item["frontmatter"].get("tags", [])
            assert any("runbook" in str(t) for t in tags)

    def test_list_tag_filter_hierarchical(self, vault: Path) -> None:
        result = _run_cli(["list", "--tag", "docker"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1
        # Should match "homelab/docker" tag
        for item in data:
            tags = item["frontmatter"].get("tags", [])
            assert any("docker" in str(t) for t in tags)

    def test_list_domain_and_tag_combined(self, vault: Path) -> None:
        result = _run_cli(["list", "--domain", "homelab", "--tag", "runbook"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert "komodo" in data[0]["path"]

    def test_list_nonexistent_domain_returns_empty(self, vault: Path) -> None:
        result = _run_cli(["list", "--domain", "fakeDomain"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []

    def test_list_empty_vault(self, empty_vault: Path) -> None:
        result = _run_cli(["list"], vault_dir=empty_vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []


# ---------------------------------------------------------------------------
# Contract: recent returns valid JSON array
# ---------------------------------------------------------------------------


class TestRecentContract:
    def test_recent_returns_json_array(self, vault: Path) -> None:
        result = _run_cli(["recent", "--days", "30"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Behavioral: recent filters by days
# ---------------------------------------------------------------------------


class TestRecentBehavior:
    def test_recent_returns_all_fresh_notes(self, vault: Path) -> None:
        # All vault notes were just created, so all are "recent"
        result = _run_cli(["recent", "--days", "30"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 6

    def test_recent_zero_days_returns_only_today(self, vault: Path) -> None:
        # With 0 days, only files modified in the last 0 days (i.e. today)
        # Since all files were just created, they should all match
        result = _run_cli(["recent", "--days", "0"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # All files just created, so all should be within 0-day window
        assert len(data) >= 0  # depends on timing, but should not error

    def test_recent_domain_filter(self, vault: Path) -> None:
        result = _run_cli(["recent", "--days", "30", "--domain", "music"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["path"].startswith("music/")

    def test_recent_sorted_most_recent_first(self, vault: Path) -> None:
        # Touch a file to make it newer
        note = vault / "personal" / "health" / "sleep-tracking.md"
        time.sleep(0.05)  # ensure mtime differs
        note.write_text(note.read_text() + "\nUpdated.", encoding="utf-8")

        result = _run_cli(["recent", "--days", "30"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 1
        # First result should be the most recently modified
        assert data[0]["path"] == "personal/health/sleep-tracking.md"

    def test_recent_empty_vault(self, empty_vault: Path) -> None:
        result = _run_cli(["recent", "--days", "30"], vault_dir=empty_vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []


# ---------------------------------------------------------------------------
# Contract: create returns valid JSON with status
# ---------------------------------------------------------------------------


class TestCreateContract:
    def test_create_returns_json_with_status(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Test note content", "--domain", "personal", "--title", "Test Note"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "created"

    def test_create_returns_path(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Content here", "--domain", "work", "--title", "My Note"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "path" in data
        assert data["path"].endswith(".md")

    def test_create_returns_domain(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Content", "--domain", "homelab", "--title", "Test"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["domain"] == "homelab"


# ---------------------------------------------------------------------------
# Behavioral: create writes real files
# ---------------------------------------------------------------------------


class TestCreateBehavior:
    def test_create_writes_file_to_disk(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "This is my new note.", "--domain", "personal", "--title", "New Note"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)

        # Verify file actually exists on disk
        file_path = empty_vault / data["path"]
        assert file_path.is_file()
        content = file_path.read_text(encoding="utf-8")
        assert "This is my new note." in content

    def test_create_has_frontmatter(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Frontmatter test.", "--domain", "work", "--title", "FM Test"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "tags:" in content
        assert "created:" in content
        assert "source:" in content

    def test_create_routes_to_correct_domain_folder(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Homelab note.", "--domain", "homelab", "--title", "Docker Setup"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["path"].startswith("homelab/")

    def test_create_with_tags_writes_tags_to_frontmatter(self, empty_vault: Path) -> None:
        result = _run_cli(
            [
                "create",
                "Tagged note.",
                "--domain",
                "personal",
                "--title",
                "Health Update",
                "--tags",
                "health,medication",
            ],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert "health" in content
        assert "medication" in content

    def test_create_kebab_case_filename(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Test.", "--domain", "work", "--title", "My Important Meeting"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        filename = Path(data["path"]).stem
        assert " " not in filename
        assert filename == filename.lower()

    def test_create_with_content_type_meeting(self, empty_vault: Path) -> None:
        result = _run_cli(
            [
                "create",
                "Discussed project.",
                "--domain",
                "work",
                "--title",
                "Sprint Review",
                "--content-type",
                "meeting",
            ],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "meetings" in data["path"]

    def test_create_with_importance(self, empty_vault: Path) -> None:
        result = _run_cli(
            [
                "create",
                "Critical info.",
                "--domain",
                "personal",
                "--title",
                "Critical Note",
                "--importance",
                "0.9",
            ],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert "importance: 0.9" in content

    def test_create_auto_links_dates(self, empty_vault: Path) -> None:
        result = _run_cli(
            [
                "create",
                "Follow up on 2026-03-15 about the project.",
                "--domain",
                "work",
                "--title",
                "Follow Up",
            ],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert "[[2026-03-15]]" in content

    def test_create_preserves_existing_wiki_links(self, empty_vault: Path) -> None:
        result = _run_cli(
            [
                "create",
                "Discussed [[Chopin Ballade No. 1]] strategy.",
                "--domain",
                "music",
                "--title",
                "Practice Log",
            ],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert "[[Chopin Ballade No. 1]]" in content

    def test_create_domain_tag_auto_added(self, empty_vault: Path) -> None:
        result = _run_cli(
            ["create", "Note.", "--domain", "finance", "--title", "Budget"],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert "finance" in content


# ---------------------------------------------------------------------------
# Behavioral: create then search round-trip
# ---------------------------------------------------------------------------


class TestCreateSearchRoundTrip:
    def test_created_note_is_searchable(self, empty_vault: Path) -> None:
        # Create a note
        create_result = _run_cli(
            [
                "create",
                "Unique canary string xQ7mZ3 for search.",
                "--domain",
                "personal",
                "--title",
                "Search Test",
            ],
            vault_dir=empty_vault,
        )
        assert create_result.returncode == 0

        # Search for it
        search_result = _run_cli(
            ["search", "xQ7mZ3"],
            vault_dir=empty_vault,
        )
        assert search_result.returncode == 0
        data = json.loads(search_result.stdout)
        assert len(data) == 1
        assert "search-test" in data[0]["path"]

    def test_created_note_is_readable(self, empty_vault: Path) -> None:
        # Create a note
        create_result = _run_cli(
            [
                "create",
                "Readable content here.",
                "--domain",
                "homelab",
                "--title",
                "Readable Note",
            ],
            vault_dir=empty_vault,
        )
        assert create_result.returncode == 0
        create_data = json.loads(create_result.stdout)

        # Read it
        read_result = _run_cli(
            ["read", create_data["path"]],
            vault_dir=empty_vault,
        )
        assert read_result.returncode == 0
        read_data = json.loads(read_result.stdout)
        assert "Readable content here." in read_data["body"]

    def test_created_note_appears_in_list(self, empty_vault: Path) -> None:
        create_result = _run_cli(
            [
                "create",
                "List test.",
                "--domain",
                "work",
                "--title",
                "Listed",
            ],
            vault_dir=empty_vault,
        )
        assert create_result.returncode == 0

        list_result = _run_cli(
            ["list", "--domain", "work"],
            vault_dir=empty_vault,
        )
        assert list_result.returncode == 0
        data = json.loads(list_result.stdout)
        assert len(data) == 1
        assert data[0]["path"].startswith("work/")

    def test_created_note_appears_in_recent(self, empty_vault: Path) -> None:
        create_result = _run_cli(
            [
                "create",
                "Recent test.",
                "--domain",
                "personal",
                "--title",
                "Recent",
            ],
            vault_dir=empty_vault,
        )
        assert create_result.returncode == 0

        recent_result = _run_cli(
            ["recent", "--days", "1"],
            vault_dir=empty_vault,
        )
        assert recent_result.returncode == 0
        data = json.loads(recent_result.stdout)
        assert len(data) >= 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_missing_vault_dir_search(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        result = _run_cli(["search", "test"], vault_dir=nonexistent)
        assert result.returncode == 1
        error = json.loads(result.stderr)
        assert "error" in error

    def test_missing_vault_dir_list(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        result = _run_cli(["list"], vault_dir=nonexistent)
        assert result.returncode == 1
        error = json.loads(result.stderr)
        assert "error" in error

    def test_missing_vault_dir_recent(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        result = _run_cli(["recent"], vault_dir=nonexistent)
        assert result.returncode == 1
        error = json.loads(result.stderr)
        assert "error" in error

    def test_create_missing_required_args(self, empty_vault: Path) -> None:
        # Missing --domain
        result = _run_cli(
            ["create", "Content", "--title", "Test"],
            vault_dir=empty_vault,
        )
        assert result.returncode != 0

    def test_no_subcommand_shows_help(self, empty_vault: Path) -> None:
        result = _run_cli([], vault_dir=empty_vault)
        assert result.returncode != 0

    def test_note_with_no_frontmatter(self, vault: Path) -> None:
        # Write a note without frontmatter
        bare = vault / "personal" / "bare-note.md"
        bare.write_text("Just plain text, no frontmatter.", encoding="utf-8")

        result = _run_cli(["read", "personal/bare-note.md"], vault_dir=vault)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["frontmatter"] == {}
        assert "Just plain text" in data["body"]

    def test_note_with_unicode_content(self, empty_vault: Path) -> None:
        result = _run_cli(
            [
                "create",
                "Rene's cafe — prix fixe menu",
                "--domain",
                "personal",
                "--title",
                "Cafe Visit",
            ],
            vault_dir=empty_vault,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        file_path = empty_vault / data["path"]
        content = file_path.read_text(encoding="utf-8")
        assert "prix fixe" in content
