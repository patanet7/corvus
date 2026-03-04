"""Contract tests for Obsidian tools against a fake Obsidian REST API server.

NO mocks. Real HTTP requests to a real BaseHTTPRequestHandler server.
Tests verify the tool→API contract: input shapes, output shapes, status codes.
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


@contextmanager
def _unconfigured_obsidian():
    """Temporarily clear obsidian module config and restore afterward."""
    from corvus.tools import obsidian as mod

    saved_url, saved_key = mod._base_url, mod._api_key
    mod._base_url = None
    mod._api_key = None
    try:
        yield
    finally:
        mod._base_url = saved_url
        mod._api_key = saved_key


@pytest.fixture(autouse=True)
def _obsidian_server():
    """Start a fresh fake Obsidian server and configure tools for each test."""
    server, base_url = start_fake_obsidian_server()
    configure(base_url, FAKE_TOKEN)
    yield base_url
    server.shutdown()


def _parse_tool_content(result: dict) -> dict:
    """Extract and parse the JSON text from a tool response."""
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# obsidian_search
# ---------------------------------------------------------------------------


class TestObsidianSearch:
    """Tests for obsidian_search tool."""

    def test_search_returns_matching_notes(self) -> None:
        result = obsidian_search(query="Claw")
        data = _parse_tool_content(result)
        assert "results" in data
        assert len(data["results"]) > 0
        filenames = [r["filename"] for r in data["results"]]
        assert "projects/openclaw.md" in filenames

    def test_search_returns_empty_for_no_match(self) -> None:
        result = obsidian_search(query="nonexistent_term_xyz123")
        data = _parse_tool_content(result)
        assert data["results"] == []

    def test_search_result_has_expected_shape(self) -> None:
        result = obsidian_search(query="daily")
        data = _parse_tool_content(result)
        assert len(data["results"]) > 0
        first = data["results"][0]
        assert "filename" in first
        assert "score" in first
        assert "matches" in first
        assert len(first["matches"]) > 0
        match = first["matches"][0]
        assert "context" in match
        assert "match" in match
        assert "start" in match["match"]
        assert "end" in match["match"]

    def test_search_context_length_param(self) -> None:
        result = obsidian_search(query="Claw", context_length=20)
        data = _parse_tool_content(result)
        assert len(data["results"]) > 0
        # With short context, context strings should be shorter
        for r in data["results"]:
            for m in r["matches"]:
                assert len(m["context"]) <= 50  # 20 chars context + query + margin

    def test_search_response_shape(self) -> None:
        result = obsidian_search(query="daily")
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    def test_search_empty_query_returns_error(self) -> None:
        result = obsidian_search(query="")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_search_whitespace_query_returns_error(self) -> None:
        result = obsidian_search(query="   ")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_search_with_ampersand_in_query(self) -> None:
        """Queries with & must be URL-encoded properly, not split params."""
        result = obsidian_search(query="foo&bar")
        data = _parse_tool_content(result)
        assert "results" in data  # Should not 400 or error from bad encoding

    def test_search_with_spaces_in_query(self) -> None:
        """Queries with spaces must be URL-encoded properly."""
        result = obsidian_search(query="daily note planning")
        data = _parse_tool_content(result)
        assert "results" in data

    def test_search_with_unicode_query(self) -> None:
        """Unicode queries must be handled correctly."""
        result = obsidian_search(query="日本語テスト")
        data = _parse_tool_content(result)
        assert "results" in data

    def test_search_content_is_sanitized(self) -> None:
        """Search results must not leak credentials."""
        obsidian_write(
            path="secrets/leak.md",
            content="My secret: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
        )
        result = obsidian_search(query="secret")
        data = _parse_tool_content(result)
        raw = json.dumps(data)
        assert "eyJhbGciOiJ" not in raw
        assert "[REDACTED]" in raw


# ---------------------------------------------------------------------------
# obsidian_read
# ---------------------------------------------------------------------------


class TestObsidianRead:
    """Tests for obsidian_read tool."""

    def test_read_existing_note(self) -> None:
        result = obsidian_read(path="journal/2026-02-27.md")
        data = _parse_tool_content(result)
        assert "content" in data
        assert "Daily Note" in data["content"]
        assert data["path"] == "journal/2026-02-27.md"

    def test_read_returns_frontmatter(self) -> None:
        result = obsidian_read(path="projects/openclaw.md")
        data = _parse_tool_content(result)
        assert "frontmatter" in data
        assert data["frontmatter"]["project"] == "Claw"

    def test_read_returns_stat_and_tags(self) -> None:
        result = obsidian_read(path="journal/2026-02-27.md")
        data = _parse_tool_content(result)
        assert "stat" in data
        assert "ctime" in data["stat"]
        assert "mtime" in data["stat"]
        assert "size" in data["stat"]
        assert "tags" in data
        assert isinstance(data["tags"], list)

    def test_read_missing_note_returns_error(self) -> None:
        result = obsidian_read(path="nonexistent/note.md")
        data = _parse_tool_content(result)
        assert "error" in data

    def test_read_rejects_path_traversal(self) -> None:
        result = obsidian_read(path="../etc/passwd")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "traversal" in data["error"].lower()

    def test_read_rejects_absolute_path(self) -> None:
        result = obsidian_read(path="/etc/passwd")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "absolute" in data["error"].lower()

    def test_read_rejects_empty_path(self) -> None:
        result = obsidian_read(path="")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_read_content_is_sanitized(self) -> None:
        """Note content must not leak credentials."""
        obsidian_write(
            path="secrets/creds.md",
            content="Token is: Bearer eyJsecrettoken123456.payload.sig",
        )
        result = obsidian_read(path="secrets/creds.md")
        data = _parse_tool_content(result)
        assert "eyJsecrettoken" not in data["content"]
        assert "[REDACTED]" in data["content"]


# ---------------------------------------------------------------------------
# obsidian_write
# ---------------------------------------------------------------------------


class TestObsidianWrite:
    """Tests for obsidian_write tool."""

    def test_write_new_note_returns_created(self) -> None:
        result = obsidian_write(
            path="test/new-note.md",
            content="# Test Note\n\nThis is a test.",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "created"
        assert data["path"] == "test/new-note.md"

    def test_write_existing_note_returns_updated(self) -> None:
        # journal/2026-02-27.md already exists in SAMPLE_NOTES
        result = obsidian_write(
            path="journal/2026-02-27.md",
            content="# Updated daily note",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "updated"

    def test_write_then_read_roundtrip(self) -> None:
        obsidian_write(path="test/roundtrip.md", content="Hello from test!")
        result = obsidian_read(path="test/roundtrip.md")
        data = _parse_tool_content(result)
        assert "Hello from test!" in data["content"]

    def test_write_overwrites_existing_note(self) -> None:
        obsidian_write(path="test/overwrite.md", content="Version 1")
        obsidian_write(path="test/overwrite.md", content="Version 2")
        result = obsidian_read(path="test/overwrite.md")
        data = _parse_tool_content(result)
        assert "Version 2" in data["content"]
        assert "Version 1" not in data["content"]

    def test_write_rejects_path_traversal(self) -> None:
        result = obsidian_write(path="../../etc/evil.md", content="pwned")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "traversal" in data["error"].lower()

    def test_write_rejects_absolute_path(self) -> None:
        result = obsidian_write(path="/etc/evil.md", content="pwned")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "absolute" in data["error"].lower()

    def test_write_rejects_empty_path(self) -> None:
        result = obsidian_write(path="", content="content")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_write_rejects_empty_content(self) -> None:
        result = obsidian_write(path="test/empty.md", content="")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"].lower()


# ---------------------------------------------------------------------------
# obsidian_append
# ---------------------------------------------------------------------------


class TestObsidianAppend:
    """Tests for obsidian_append tool."""

    def test_append_to_existing_note(self) -> None:
        result = obsidian_append(
            path="journal/2026-02-27.md",
            content="\n\n## Evening\nDone for the day.",
        )
        data = _parse_tool_content(result)
        assert data["status"] == "ok"

    def test_append_then_read_shows_combined(self) -> None:
        obsidian_append(
            path="journal/2026-02-27.md",
            content="\n\n## Evening\nDone for the day.",
        )
        read_result = obsidian_read(path="journal/2026-02-27.md")
        read_data = _parse_tool_content(read_result)
        assert "Evening" in read_data["content"]
        assert "Daily Note" in read_data["content"]

    def test_append_to_nonexistent_creates_note(self) -> None:
        result = obsidian_append(path="test/new-append.md", content="First line")
        data = _parse_tool_content(result)
        assert data["status"] == "ok"

        read_result = obsidian_read(path="test/new-append.md")
        read_data = _parse_tool_content(read_result)
        assert "First line" in read_data["content"]

    def test_append_rejects_path_traversal(self) -> None:
        result = obsidian_append(path="../etc/evil", content="pwned")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "traversal" in data["error"].lower()

    def test_append_rejects_absolute_path(self) -> None:
        result = obsidian_append(path="/etc/evil", content="pwned")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "absolute" in data["error"].lower()

    def test_append_rejects_empty_content(self) -> None:
        result = obsidian_append(path="test/file.md", content="")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_multiple_appends_accumulate(self) -> None:
        obsidian_write(path="test/multi.md", content="Line 1")
        obsidian_append(path="test/multi.md", content="\nLine 2")
        obsidian_append(path="test/multi.md", content="\nLine 3")
        result = obsidian_read(path="test/multi.md")
        data = _parse_tool_content(result)
        assert "Line 1" in data["content"]
        assert "Line 2" in data["content"]
        assert "Line 3" in data["content"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestObsidianAuth:
    """Tests that bad auth token returns error for all tools."""

    @pytest.fixture(autouse=True)
    def _bad_token(self, _obsidian_server: str) -> None:
        """Reconfigure with a bad token for this class only."""
        configure(_obsidian_server, "bad-token-invalid")

    def test_search_with_bad_token(self) -> None:
        result = obsidian_search(query="test")
        data = _parse_tool_content(result)
        assert "error" in data

    def test_read_with_bad_token(self) -> None:
        result = obsidian_read(path="journal/2026-02-27.md")
        data = _parse_tool_content(result)
        assert "error" in data

    def test_write_with_bad_token(self) -> None:
        result = obsidian_write(path="test/auth.md", content="test")
        data = _parse_tool_content(result)
        assert "error" in data

    def test_append_with_bad_token(self) -> None:
        result = obsidian_append(path="test/auth.md", content="test")
        data = _parse_tool_content(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------


class TestObsidianConfigError:
    """Tests that unconfigured tools return error responses."""

    def test_search_unconfigured(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_search(query="test")
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"].lower()

    def test_read_unconfigured(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_read(path="journal/2026-02-27.md")
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"].lower()

    def test_write_unconfigured(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_write(path="test/cfg.md", content="test")
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"].lower()

    def test_append_unconfigured(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_append(path="test/cfg.md", content="test")
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"].lower()
