"""Tests for Firefly III MCP tools.

Pure-function tests run without external deps.
Live contract tests are skipped when FIREFLY_URL is not set.

NO MOCKS — all tests exercise real code paths.
"""

import json
import os

import pytest

from corvus.tools.firefly import (
    _format_transaction,
    _get_config,
    configure,
    firefly_accounts,
    firefly_categories,
    firefly_create_transaction,
    firefly_summary,
    firefly_transactions,
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
        msg = "Authorization: Bearer abc123def456ghi789jklmnopqrst"
        result = _make_error_response(msg)
        raw = result["content"][0]["text"]
        assert "abc123def456" not in raw
        assert "[REDACTED]" in raw


class TestConfigure:
    """Tests for configure() and _get_config()."""

    def test_configure_sets_url_and_token(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            configure("http://localhost:8081", "test-token-abc123")
            assert mod._firefly_url == "http://localhost:8081"
            assert mod._firefly_token == "test-token-abc123"
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_configure_strips_trailing_slash(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            configure("http://localhost:8081/", "test-token")
            assert mod._firefly_url == "http://localhost:8081"
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_get_config_raises_when_unconfigured(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            mod._firefly_url = None
            mod._firefly_token = None
            with pytest.raises(RuntimeError, match="not configured"):
                _get_config()
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_get_config_returns_tuple_when_configured(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            configure("http://host:8081", "my-token")
            url, token = _get_config()
            assert url == "http://host:8081"
            assert token == "my-token"
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token


class TestToolFunctionsAreSync:
    """Verify all 5 tool functions are plain sync functions (match ha.py pattern)."""

    def test_firefly_transactions_is_sync(self) -> None:
        import inspect

        assert callable(firefly_transactions)
        assert not inspect.iscoroutinefunction(firefly_transactions)

    def test_firefly_accounts_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(firefly_accounts)

    def test_firefly_categories_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(firefly_categories)

    def test_firefly_summary_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(firefly_summary)

    def test_firefly_create_transaction_is_sync(self) -> None:
        import inspect

        assert not inspect.iscoroutinefunction(firefly_create_transaction)


class TestFormatTransaction:
    """Tests for _format_transaction helper."""

    def test_basic_fields(self) -> None:
        entry = {"id": "42"}
        tx = {
            "date": "2026-02-15",
            "description": "Grocery run",
            "amount": "52.30",
            "currency_code": "USD",
            "type": "withdrawal",
            "source_name": "Checking",
            "destination_name": "Trader Joe's",
            "category_name": "Groceries",
            "budget_name": "Food",
        }
        result = _format_transaction(entry, tx)
        assert result["id"] == "42"
        assert result["date"] == "2026-02-15"
        assert result["description"] == "Grocery run"
        assert result["amount"] == "52.30"
        assert result["currency_code"] == "USD"
        assert result["type"] == "withdrawal"
        assert result["source_name"] == "Checking"
        assert result["destination_name"] == "Trader Joe's"
        assert result["category_name"] == "Groceries"
        assert result["budget_name"] == "Food"

    def test_missing_optional_fields_use_defaults(self) -> None:
        entry = {"id": "1"}
        tx = {}
        result = _format_transaction(entry, tx)
        assert result["id"] == "1"
        assert result["date"] == ""
        assert result["description"] == ""
        assert result["amount"] == "0"
        assert result["currency_code"] == ""
        assert result["type"] == ""
        assert result["source_name"] == ""
        assert result["destination_name"] == ""
        assert result["category_name"] == ""
        assert result["budget_name"] == ""

    def test_entry_without_id(self) -> None:
        entry = {}
        tx = {"description": "Test"}
        result = _format_transaction(entry, tx)
        assert result["id"] is None
        assert result["description"] == "Test"


class TestInputValidation:
    """Tests for input validation in tool functions (no network needed)."""

    def test_create_transaction_missing_description_raises_type_error(self) -> None:
        """Python enforces required positional arg 'description'."""
        with pytest.raises(TypeError):
            firefly_create_transaction(amount="10.00")  # type: ignore[call-arg]

    def test_create_transaction_missing_amount_raises_type_error(self) -> None:
        """Python enforces required positional arg 'amount'."""
        with pytest.raises(TypeError):
            firefly_create_transaction(description="Test purchase")  # type: ignore[call-arg]

    def test_create_transaction_missing_both_raises_type_error(self) -> None:
        """Python enforces both required args."""
        with pytest.raises(TypeError):
            firefly_create_transaction()  # type: ignore[call-arg]

    def test_transactions_unconfigured_returns_error(self) -> None:
        """When module is not configured, tool functions return error gracefully."""
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            mod._firefly_url = None
            mod._firefly_token = None
            result = firefly_transactions()
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"]
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_accounts_unconfigured_returns_error(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            mod._firefly_url = None
            mod._firefly_token = None
            result = firefly_accounts()
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"]
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_categories_unconfigured_returns_error(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            mod._firefly_url = None
            mod._firefly_token = None
            result = firefly_categories()
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"]
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_summary_unconfigured_returns_error(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            mod._firefly_url = None
            mod._firefly_token = None
            result = firefly_summary()
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"]
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token

    def test_create_transaction_unconfigured_returns_error(self) -> None:
        from corvus.tools import firefly as mod

        saved_url, saved_token = mod._firefly_url, mod._firefly_token
        try:
            mod._firefly_url = None
            mod._firefly_token = None
            result = firefly_create_transaction(description="Test", amount="5.00")
            data = _parse_tool_content(result)
            assert "error" in data
            assert "not configured" in data["error"]
        finally:
            mod._firefly_url = saved_url
            mod._firefly_token = saved_token


# ---------------------------------------------------------------------------
# Live contract tests (skipped when FIREFLY_URL is not set)
# ---------------------------------------------------------------------------

_has_firefly = bool(os.environ.get("FIREFLY_URL"))
_skip_reason = "FIREFLY_URL not set — skipping live Firefly contract tests"


@pytest.fixture(autouse=True)
def _configure_live():
    """Configure firefly tools from env vars for live tests."""
    url = os.environ.get("FIREFLY_URL", "")
    token = os.environ.get("FIREFLY_API_TOKEN", "")
    if url and token:
        configure(url, token)


@pytest.mark.live
@pytest.mark.skipif(not _has_firefly, reason=_skip_reason)
class TestLiveFireflyAccounts:
    """Live contract tests for firefly_accounts."""

    def test_accounts_returns_tool_response_with_accounts(self) -> None:
        result = firefly_accounts()
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        data = _parse_tool_content(result)
        assert "accounts" in data
        assert isinstance(data["accounts"], list)

    def test_accounts_have_expected_fields(self) -> None:
        result = firefly_accounts()
        data = _parse_tool_content(result)
        if len(data["accounts"]) > 0:
            acct = data["accounts"][0]
            assert "id" in acct
            assert "name" in acct
            assert "type" in acct
            assert "current_balance" in acct
            assert "currency_code" in acct
            assert "active" in acct

    def test_accounts_type_filter(self) -> None:
        result = firefly_accounts(type="asset")
        data = _parse_tool_content(result)
        assert "accounts" in data
        # All returned accounts should be asset type
        for acct in data["accounts"]:
            assert acct["type"] == "asset"


@pytest.mark.live
@pytest.mark.skipif(not _has_firefly, reason=_skip_reason)
class TestLiveFireflyTransactions:
    """Live contract tests for firefly_transactions."""

    def test_transactions_returns_tool_response_with_count(self) -> None:
        result = firefly_transactions()
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        data = _parse_tool_content(result)
        assert "count" in data
        assert "transactions" in data
        assert isinstance(data["transactions"], list)

    def test_transactions_have_expected_fields(self) -> None:
        result = firefly_transactions()
        data = _parse_tool_content(result)
        if data["count"] > 0:
            tx = data["transactions"][0]
            assert "id" in tx
            assert "date" in tx
            assert "description" in tx
            assert "amount" in tx
            assert "type" in tx
            assert "source_name" in tx
            assert "destination_name" in tx
