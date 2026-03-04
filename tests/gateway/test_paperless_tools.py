"""Tests for Paperless-ngx MCP tools.

Pure-function tests run without external deps.
Live contract tests are skipped when PAPERLESS_URL is not set.

NO MOCKS — all tests exercise real code paths.
"""

import json
import os

import pytest

from corvus.tools.paperless import (
    _format_document,
    _get_config,
    configure,
    paperless_bulk_edit,
    paperless_read,
    paperless_search,
    paperless_tag,
    paperless_tags,
)
from corvus.tools.response import make_error_response as _make_error_response
from corvus.tools.response import make_tool_response as _make_tool_response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tool_content(result: dict) -> dict:
    """Extract and parse the JSON text from a tool response."""
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# Pure-function tests (always run, no external deps)
# ---------------------------------------------------------------------------


class TestMakeToolResponse:
    """Tests for _make_tool_response wrapper."""

    def test_wraps_dict_data(self) -> None:
        result = _make_tool_response({"count": 5, "items": []})
        assert "content" in result
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == {"count": 5, "items": []}

    def test_wraps_list_data(self) -> None:
        result = _make_tool_response([1, 2, 3])
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == [1, 2, 3]

    def test_wraps_string_data(self) -> None:
        result = _make_tool_response("hello")
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == "hello"


class TestMakeErrorResponse:
    """Tests for _make_error_response wrapper."""

    def test_wraps_error_message(self) -> None:
        result = _make_error_response("something went wrong")
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        parsed = json.loads(result["content"][0]["text"])
        assert parsed == {"error": "something went wrong"}


class TestSanitization:
    """Tests that credential patterns are redacted in responses."""

    def test_tool_response_sanitizes_bearer_token(self) -> None:
        data = {"token": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"}
        result = _make_tool_response(data)
        raw = result["content"][0]["text"]
        assert "eyJhbGciOiJ" not in raw
        assert "[REDACTED]" in raw

    def test_error_response_sanitizes_auth_header(self) -> None:
        msg = "Authorization: Token abc123def456ghi789jklmnopqrst"
        result = _make_error_response(msg)
        raw = result["content"][0]["text"]
        assert "abc123def456" not in raw
        assert "[REDACTED]" in raw


class TestConfigure:
    """Tests for configure() and _get_config()."""

    def test_configure_sets_url_and_token(self) -> None:
        from corvus.tools import paperless as mod

        saved_url, saved_token = mod._paperless_url, mod._paperless_token
        try:
            configure("http://localhost:8010", "test-token-abc123")
            assert mod._paperless_url == "http://localhost:8010"
            assert mod._paperless_token == "test-token-abc123"
        finally:
            mod._paperless_url = saved_url
            mod._paperless_token = saved_token

    def test_configure_strips_trailing_slash(self) -> None:
        from corvus.tools import paperless as mod

        saved_url, saved_token = mod._paperless_url, mod._paperless_token
        try:
            configure("http://localhost:8010/", "test-token")
            assert mod._paperless_url == "http://localhost:8010"
        finally:
            mod._paperless_url = saved_url
            mod._paperless_token = saved_token

    def test_get_config_raises_when_unconfigured(self) -> None:
        from corvus.tools import paperless as mod

        saved_url, saved_token = mod._paperless_url, mod._paperless_token
        try:
            mod._paperless_url = None
            mod._paperless_token = None
            with pytest.raises(RuntimeError, match="not configured"):
                _get_config()
        finally:
            mod._paperless_url = saved_url
            mod._paperless_token = saved_token

    def test_get_config_returns_tuple_when_configured(self) -> None:
        from corvus.tools import paperless as mod

        saved_url, saved_token = mod._paperless_url, mod._paperless_token
        try:
            configure("http://host:8010", "my-token")
            url, token = _get_config()
            assert url == "http://host:8010"
            assert token == "my-token"
        finally:
            mod._paperless_url = saved_url
            mod._paperless_token = saved_token


class TestToolFunctionsAreSync:
    """Verify all 5 tool functions are plain sync functions (match ha.py pattern)."""

    def test_paperless_search_is_sync(self) -> None:
        assert callable(paperless_search)
        # Not a coroutine function — sync like ha.py
        import inspect

        assert not inspect.iscoroutinefunction(paperless_search)

    def test_paperless_read_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(paperless_read)

    def test_paperless_tags_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(paperless_tags)

    def test_paperless_tag_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(paperless_tag)

    def test_paperless_bulk_edit_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(paperless_bulk_edit)


class TestFormatDocument:
    """Tests for _format_document helper."""

    def test_basic_fields(self) -> None:
        doc = {
            "id": 42,
            "title": "Invoice Q1",
            "created": "2026-01-15",
            "tags": [1, 3],
            "correspondent": 7,
            "document_type": 2,
        }
        result = _format_document(doc)
        assert result["id"] == 42
        assert result["title"] == "Invoice Q1"
        assert result["created"] == "2026-01-15"
        assert result["tags"] == [1, 3]
        assert result["correspondent"] == 7
        assert result["document_type"] == 2

    def test_missing_optional_fields_use_defaults(self) -> None:
        doc = {"id": 1, "title": "Minimal"}
        result = _format_document(doc)
        assert result["created"] == ""
        assert result["tags"] == []
        assert result["correspondent"] is None
        assert result["document_type"] is None

    def test_content_snippet_truncated_to_500(self) -> None:
        doc = {"id": 1, "title": "Long", "content": "x" * 1000}
        result = _format_document(doc)
        assert "content_snippet" in result
        assert len(result["content_snippet"]) == 500

    def test_no_content_snippet_when_no_content(self) -> None:
        doc = {"id": 1, "title": "Empty"}
        result = _format_document(doc)
        assert "content_snippet" not in result

    def test_search_hit_metadata_included(self) -> None:
        doc = {
            "id": 1,
            "title": "Hit",
            "__search_hit__": {"score": 0.95, "highlights": "found <em>here</em>"},
        }
        result = _format_document(doc)
        assert result["score"] == 0.95
        assert result["highlights"] == "found <em>here</em>"

    def test_no_search_hit_when_absent(self) -> None:
        doc = {"id": 1, "title": "No Hit"}
        result = _format_document(doc)
        assert "score" not in result
        assert "highlights" not in result


class TestInputValidation:
    """Tests for input validation in tool functions (no network needed).

    Required-arg-missing cases now raise TypeError (Python enforces it).
    Semantic validation (empty query, empty documents list) still returns
    structured error responses.
    """

    def test_search_empty_query_returns_error(self) -> None:
        result = paperless_search(query="")
        data = _parse_tool_content(result)
        assert "error" in data
        assert "empty" in data["error"]

    def test_search_whitespace_query_returns_error(self) -> None:
        result = paperless_search(query="   ")
        data = _parse_tool_content(result)
        assert "error" in data

    def test_search_missing_query_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_search()  # type: ignore[call-arg]

    def test_read_missing_id_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_read()  # type: ignore[call-arg]

    def test_tag_missing_id_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_tag(tag="inbox")  # type: ignore[call-arg]

    def test_tag_missing_tag_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_tag(id=1)  # type: ignore[call-arg]

    def test_bulk_edit_missing_documents_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_bulk_edit(method="add_tag", parameters={"tag": 1})  # type: ignore[call-arg]

    def test_bulk_edit_empty_documents_returns_error(self) -> None:
        result = paperless_bulk_edit(documents=[], method="add_tag", parameters={"tag": 1})
        data = _parse_tool_content(result)
        assert "error" in data

    def test_bulk_edit_missing_method_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_bulk_edit(documents=[1], parameters={"tag": 1})  # type: ignore[call-arg]

    def test_bulk_edit_missing_parameters_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            paperless_bulk_edit(documents=[1], method="add_tag")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Live contract tests (skipped when PAPERLESS_URL is not set)
# ---------------------------------------------------------------------------

_has_paperless = bool(os.environ.get("PAPERLESS_URL"))
_skip_reason = "PAPERLESS_URL not set — skipping live Paperless contract tests"


@pytest.fixture(autouse=True, scope="module")
def _configure_live():
    """Configure paperless tools from env vars for live tests."""
    url = os.environ.get("PAPERLESS_URL", "")
    token = os.environ.get("PAPERLESS_API_TOKEN", "")
    if url and token:
        configure(url, token)


@pytest.mark.skipif(not _has_paperless, reason=_skip_reason)
class TestLivePaperlessSearch:
    """Live contract tests for paperless_search."""

    def test_search_returns_tool_response_with_count_and_documents(self) -> None:
        result = paperless_search(query="invoice")
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        data = _parse_tool_content(result)
        assert "count" in data
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_search_documents_have_expected_fields(self) -> None:
        result = paperless_search(query="invoice")
        data = _parse_tool_content(result)
        if data["count"] > 0:
            doc = data["documents"][0]
            assert "id" in doc
            assert "title" in doc
            assert "created" in doc
            assert "tags" in doc


@pytest.mark.skipif(not _has_paperless, reason=_skip_reason)
class TestLivePaperlessTags:
    """Live contract tests for paperless_tags."""

    def test_tags_returns_list(self) -> None:
        result = paperless_tags()
        assert "content" in result
        data = _parse_tool_content(result)
        assert "tags" in data
        assert isinstance(data["tags"], list)

    def test_tags_have_expected_fields(self) -> None:
        result = paperless_tags()
        data = _parse_tool_content(result)
        if len(data["tags"]) > 0:
            tag = data["tags"][0]
            assert "id" in tag
            assert "name" in tag
