"""Contract tests for Obsidian allowed_prefixes path isolation.

NO mocks. Real HTTP requests to a real BaseHTTPRequestHandler server.
Tests verify that allowed_prefixes restricts read/write/append/search
to only the specified vault subtrees.
"""

import json
from contextlib import contextmanager

import pytest

from corvus.tools.obsidian import (
    configure,
    obsidian_append,
    obsidian_read,
    obsidian_search,
    obsidian_write,
)
from tests.contracts.fake_obsidian_api import (
    FAKE_TOKEN,
    start_fake_obsidian_server,
)


def _parse_tool_content(result: dict) -> dict:
    """Extract and parse the JSON text from a tool response."""
    return json.loads(result["content"][0]["text"])


@contextmanager
def _reset_prefix():
    """Reset the module-level client to restore prefix state after use."""
    from corvus.tools import obsidian as mod

    saved_client = mod._client
    try:
        yield
    finally:
        mod._client = saved_client


@pytest.fixture(autouse=True)
def _obsidian_server():
    """Start a fresh fake Obsidian server and configure tools for each test."""
    server, base_url = start_fake_obsidian_server()
    configure(base_url, FAKE_TOKEN)
    yield base_url
    server.shutdown()


# ---------------------------------------------------------------------------
# Write prefix enforcement
# ---------------------------------------------------------------------------


class TestWritePrefix:
    """Tests for obsidian_write with allowed_prefixes."""

    def test_write_to_allowed_prefix_succeeds(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_write(path="personal/note.md", content="Hello")
        data = _parse_tool_content(result)
        assert "error" not in data
        assert data["path"] == "personal/note.md"

    def test_write_to_blocked_prefix_returns_error(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_write(path="work/secret.md", content="Nope")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()

    def test_write_to_nested_allowed_path(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_write(path="personal/sub/deep/note.md", content="Deep")
        data = _parse_tool_content(result)
        assert "error" not in data
        assert data["path"] == "personal/sub/deep/note.md"


# ---------------------------------------------------------------------------
# Append prefix enforcement
# ---------------------------------------------------------------------------


class TestAppendPrefix:
    """Tests for obsidian_append with allowed_prefixes."""

    def test_append_to_allowed_prefix_succeeds(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["journal/"])
        result = obsidian_append(path="journal/2026-02-27.md", content="\nExtra line")
        data = _parse_tool_content(result)
        assert "error" not in data
        assert data["status"] == "ok"

    def test_append_to_blocked_prefix_returns_error(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["journal/"])
        result = obsidian_append(path="projects/openclaw.md", content="Nope")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()


# ---------------------------------------------------------------------------
# Read prefix enforcement
# ---------------------------------------------------------------------------


class TestReadPrefix:
    """Tests for obsidian_read with allowed_prefixes."""

    def test_read_from_allowed_prefix_succeeds(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["journal/"])
        result = obsidian_read(path="journal/2026-02-27.md")
        data = _parse_tool_content(result)
        assert "error" not in data
        assert "content" in data

    def test_read_from_blocked_prefix_returns_error(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["journal/"])
        result = obsidian_read(path="projects/openclaw.md")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()


# ---------------------------------------------------------------------------
# Search prefix filtering
# ---------------------------------------------------------------------------


class TestSearchPrefix:
    """Tests for obsidian_search with allowed_prefixes filtering."""

    def test_search_returns_only_allowed_prefix_results(self, _obsidian_server: str) -> None:
        """Seed notes in multiple prefixes; only allowed ones returned."""
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        # "personal/todo.md" exists in SAMPLE_NOTES, "projects/openclaw.md" also.
        # Search for a term that appears in both personal and projects notes.
        # First seed a personal note with "OpenClaw" so it matches.
        with _reset_prefix():
            configure(_obsidian_server, FAKE_TOKEN)  # unrestricted for seeding
            obsidian_write(
                path="personal/claw-note.md",
                content="Working on OpenClaw today.",
            )
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_search(query="OpenClaw")
        data = _parse_tool_content(result)
        filenames = [r["filename"] for r in data["results"]]
        # Only personal/ results should appear
        for fn in filenames:
            assert fn.startswith("personal/"), f"Unexpected result: {fn}"
        assert len(filenames) > 0  # at least the seeded note

    def test_search_excludes_blocked_prefix(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["journal/"])
        result = obsidian_search(query="OpenClaw")
        data = _parse_tool_content(result)
        filenames = [r["filename"] for r in data["results"]]
        # projects/openclaw.md should NOT appear
        assert "projects/openclaw.md" not in filenames


# ---------------------------------------------------------------------------
# Default behavior (no prefix restriction)
# ---------------------------------------------------------------------------


class TestNoPrefixRestriction:
    """Tests that allowed_prefixes=None (default) means unrestricted."""

    def test_default_configure_allows_all_reads(self) -> None:
        """Default configure (no allowed_prefixes) allows reading any path."""
        result = obsidian_read(path="projects/openclaw.md")
        data = _parse_tool_content(result)
        assert "error" not in data
        assert "content" in data

    def test_default_configure_allows_all_writes(self) -> None:
        result = obsidian_write(path="work/note.md", content="Allowed")
        data = _parse_tool_content(result)
        assert "error" not in data

    def test_default_configure_allows_all_appends(self) -> None:
        result = obsidian_append(path="journal/2026-02-27.md", content="\nMore")
        data = _parse_tool_content(result)
        assert "error" not in data

    def test_default_configure_returns_all_search_results(self) -> None:
        result = obsidian_search(query="Claw")
        data = _parse_tool_content(result)
        filenames = [r["filename"] for r in data["results"]]
        assert "projects/openclaw.md" in filenames

    def test_explicit_none_means_unrestricted(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=None)
        result = obsidian_read(path="projects/openclaw.md")
        data = _parse_tool_content(result)
        assert "error" not in data


# ---------------------------------------------------------------------------
# Empty prefix list (blocks everything)
# ---------------------------------------------------------------------------


class TestEmptyPrefixList:
    """Tests that allowed_prefixes=[] blocks all paths."""

    def test_empty_list_blocks_read(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=[])
        result = obsidian_read(path="journal/2026-02-27.md")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()

    def test_empty_list_blocks_write(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=[])
        result = obsidian_write(path="any/note.md", content="Blocked")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()

    def test_empty_list_blocks_append(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=[])
        result = obsidian_append(path="any/note.md", content="Blocked")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()

    def test_empty_list_returns_no_search_results(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=[])
        result = obsidian_search(query="OpenClaw")
        data = _parse_tool_content(result)
        assert data["results"] == []


# ---------------------------------------------------------------------------
# Defense in depth: traversal + prefix
# ---------------------------------------------------------------------------


class TestTraversalWithPrefix:
    """Traversal attacks are still blocked when prefix is set."""

    def test_traversal_blocked_with_prefix(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_read(path="../etc/passwd")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "traversal" in data["error"].lower()

    def test_absolute_path_blocked_with_prefix(self, _obsidian_server: str) -> None:
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_write(path="/etc/evil.md", content="pwned")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "absolute" in data["error"].lower()


# ---------------------------------------------------------------------------
# Partial prefix matching
# ---------------------------------------------------------------------------


class TestPartialPrefixMatch:
    """Ensure partial prefix doesn't falsely match."""

    def test_partial_prefix_does_not_match(self, _obsidian_server: str) -> None:
        """'personal/' should NOT match 'personalstuff/note.md'."""
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal/"])
        result = obsidian_write(path="personalstuff/note.md", content="Nope")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()

    def test_prefix_without_trailing_slash_matches_broadly(self, _obsidian_server: str) -> None:
        """'personal' (no slash) would match 'personalstuff/' — use trailing slash."""
        configure(_obsidian_server, FAKE_TOKEN, allowed_prefixes=["personal"])
        # "personal" prefix matches "personalstuff/" because startswith("personal")
        result = obsidian_write(path="personalstuff/note.md", content="Broad")
        data = _parse_tool_content(result)
        # This succeeds because "personalstuff/..." starts with "personal"
        assert "error" not in data


# ---------------------------------------------------------------------------
# Multiple prefixes
# ---------------------------------------------------------------------------


class TestMultiplePrefixes:
    """Tests with multiple allowed prefixes."""

    def test_multiple_prefixes_allow_matching_paths(self, _obsidian_server: str) -> None:
        configure(
            _obsidian_server,
            FAKE_TOKEN,
            allowed_prefixes=["personal/", "journal/"],
        )
        r1 = obsidian_read(path="personal/todo.md")
        r2 = obsidian_read(path="journal/2026-02-27.md")
        assert "error" not in _parse_tool_content(r1)
        assert "error" not in _parse_tool_content(r2)

    def test_multiple_prefixes_block_non_matching(self, _obsidian_server: str) -> None:
        configure(
            _obsidian_server,
            FAKE_TOKEN,
            allowed_prefixes=["personal/", "journal/"],
        )
        result = obsidian_read(path="projects/openclaw.md")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "not allowed" in data["error"].lower()

    def test_error_message_lists_permitted_prefixes(self, _obsidian_server: str) -> None:
        configure(
            _obsidian_server,
            FAKE_TOKEN,
            allowed_prefixes=["personal/", "journal/"],
        )
        result = obsidian_read(path="work/blocked.md")
        data = _parse_tool_content(result)
        assert "personal/" in data["error"]
        assert "journal/" in data["error"]
