"""9-part credential isolation test suite for Obsidian tools.

NO mocks. All behavioral — real HTTP against real fake servers.
Verifies that credentials never leak through tool outputs, error messages,
module state, or cross-tool boundaries.
"""

import inspect
import json
from contextlib import contextmanager

import pytest

from corvus.sanitize import sanitize
from corvus.tools import obsidian as obsidian_module
from corvus.tools.ha import (
    configure as configure_ha,
)
from corvus.tools.ha import (
    ha_get_state,
    ha_list_entities,
)
from corvus.tools.obsidian import (
    configure as configure_obsidian,
)
from corvus.tools.obsidian import (
    obsidian_append,
    obsidian_read,
    obsidian_search,
    obsidian_write,
)
from tests.contracts.fake_ha_api import FAKE_TOKEN as HA_TOKEN
from tests.contracts.fake_ha_api import start_fake_ha_server
from tests.contracts.fake_obsidian_api import (
    FAKE_TOKEN as OBSIDIAN_TOKEN,
)
from tests.contracts.fake_obsidian_api import (
    FakeObsidianHandler,
    start_fake_obsidian_server,
)


@contextmanager
def _unconfigured_obsidian():
    """Temporarily clear obsidian module config and restore afterward."""
    saved_url, saved_key = obsidian_module._base_url, obsidian_module._api_key
    obsidian_module._base_url = None
    obsidian_module._api_key = None
    try:
        yield
    finally:
        obsidian_module._base_url = saved_url
        obsidian_module._api_key = saved_key


def _all_text_from_result(result: dict) -> str:
    """Join all text blocks from a tool response into a single string."""
    return " ".join(block.get("text", "") for block in result.get("content", []))


@pytest.fixture(autouse=True)
def _both_servers():
    """Start both fake servers and configure both tool modules for each test."""
    obs_server, obs_url = start_fake_obsidian_server()
    ha_server, ha_url = start_fake_ha_server()

    configure_obsidian(obs_url, OBSIDIAN_TOKEN)
    configure_ha(ha_url, HA_TOKEN)

    FakeObsidianHandler.recorded_requests.clear()

    yield obs_url, ha_url

    obs_server.shutdown()
    ha_server.shutdown()


# ---------------------------------------------------------------------------
# 1. Tool outputs never contain credentials
# ---------------------------------------------------------------------------


class TestToolOutputsNeverContainCredentials:
    """All 4 Obsidian tool outputs must never contain the API token."""

    def test_search_output_clean(self) -> None:
        result = obsidian_search(query="daily")
        text = _all_text_from_result(result)
        assert OBSIDIAN_TOKEN not in text
        assert "Bearer" not in text

    def test_read_output_clean(self) -> None:
        result = obsidian_read(path="journal/2026-02-27.md")
        text = _all_text_from_result(result)
        assert OBSIDIAN_TOKEN not in text
        assert "Bearer" not in text

    def test_write_output_clean(self) -> None:
        result = obsidian_write(path="test/isolation.md", content="Test content")
        text = _all_text_from_result(result)
        assert OBSIDIAN_TOKEN not in text
        assert "Bearer" not in text

    def test_append_output_clean(self) -> None:
        result = obsidian_append(path="journal/2026-02-27.md", content="\nAppended.")
        text = _all_text_from_result(result)
        assert OBSIDIAN_TOKEN not in text
        assert "Bearer" not in text


# ---------------------------------------------------------------------------
# 2. Sanitization catches leaked headers
# ---------------------------------------------------------------------------


class TestSanitizationCatchesLeakedHeaders:
    """Verify sanitize() strips credential patterns."""

    def test_strips_authorization_bearer(self) -> None:
        text = f"Authorization: Bearer {OBSIDIAN_TOKEN}"
        result = sanitize(text)
        assert OBSIDIAN_TOKEN not in result
        assert "[REDACTED]" in result

    def test_strips_api_key_pattern(self) -> None:
        text = f'api_key="{OBSIDIAN_TOKEN}abcdefghijklmnop"'
        result = sanitize(text)
        assert OBSIDIAN_TOKEN not in result
        assert "[REDACTED]" in result

    def test_strips_multiple_credentials_at_once(self) -> None:
        text = (
            f"Authorization: Bearer {OBSIDIAN_TOKEN}\n"
            f"Cookie: session={HA_TOKEN}\n"
            f'api_key="{OBSIDIAN_TOKEN}extra_padding_chars"'
        )
        result = sanitize(text)
        assert OBSIDIAN_TOKEN not in result
        assert HA_TOKEN not in result
        assert result.count("[REDACTED]") >= 3


# ---------------------------------------------------------------------------
# 3. Error messages never leak credentials
# ---------------------------------------------------------------------------


class TestErrorMessagesNoCredentialLeak:
    """Error responses must never contain tokens."""

    def test_unreachable_error_clean(self) -> None:
        configure_obsidian("http://127.0.0.1:1", OBSIDIAN_TOKEN)
        result = obsidian_search(query="test")
        text = _all_text_from_result(result)
        assert OBSIDIAN_TOKEN not in text
        assert "error" in text.lower()

    def test_bad_token_error_clean(self) -> None:
        configure_obsidian(
            obsidian_module._base_url or "http://127.0.0.1:1",
            "wrong-token-12345",
        )
        result = obsidian_search(query="test")
        text = _all_text_from_result(result)
        assert "wrong-token-12345" not in text


# ---------------------------------------------------------------------------
# 4. Path traversal blocked
# ---------------------------------------------------------------------------


EVIL_PATHS = [
    "../../etc/passwd",
    "../../../secrets/claw.env",
    "/etc/passwd",
    "/Users/thomas/.secrets/claw.env",
    "journal/../../etc/passwd",
    "a/b/../../../../etc/shadow",
]


class TestPathTraversalBlocked:
    """All evil paths must return error responses and never reach the server."""

    @pytest.mark.parametrize("evil_path", EVIL_PATHS)
    def test_read_blocks_traversal(self, evil_path: str) -> None:
        result = obsidian_read(path=evil_path)
        data = json.loads(_all_text_from_result(result))
        assert "error" in data

    @pytest.mark.parametrize("evil_path", EVIL_PATHS)
    def test_write_blocks_traversal(self, evil_path: str) -> None:
        result = obsidian_write(path=evil_path, content="pwned")
        data = json.loads(_all_text_from_result(result))
        assert "error" in data

    @pytest.mark.parametrize("evil_path", EVIL_PATHS)
    def test_append_blocks_traversal(self, evil_path: str) -> None:
        result = obsidian_append(path=evil_path, content="pwned")
        data = json.loads(_all_text_from_result(result))
        assert "error" in data

    def test_no_evil_paths_reached_server(self) -> None:
        """After all traversal attempts, none should have hit the fake server."""
        for evil_path in EVIL_PATHS:
            obsidian_read(path=evil_path)
            obsidian_write(path=evil_path, content="pwned")
            obsidian_append(path=evil_path, content="pwned")

        for req in FakeObsidianHandler.recorded_requests:
            for evil in EVIL_PATHS:
                # Neither the raw evil path nor key fragments should appear
                assert evil not in req["path"]
                assert evil not in req.get("body", "")


# ---------------------------------------------------------------------------
# 5. Configure state not serializable with credentials
# ---------------------------------------------------------------------------


class TestConfigureStateNotSerializable:
    """Module public attributes must not expose the token when serialized."""

    def test_public_attrs_do_not_contain_token(self) -> None:
        public_attrs = {
            k: str(v) for k, v in vars(obsidian_module).items() if not k.startswith("_") and not callable(v)
        }
        serialized = json.dumps(public_attrs)
        assert OBSIDIAN_TOKEN not in serialized

    def test_tool_function_defaults_do_not_contain_token(self) -> None:
        for func in [obsidian_search, obsidian_read, obsidian_write, obsidian_append]:
            sig = inspect.signature(func)
            for param in sig.parameters.values():
                if param.default is not inspect.Parameter.empty:
                    assert OBSIDIAN_TOKEN not in str(param.default)


# ---------------------------------------------------------------------------
# 6. Unconfigured tools fail safely
# ---------------------------------------------------------------------------


class TestUnconfiguredToolsFailSafely:
    """Tools must return error without leaking token when unconfigured."""

    def test_unconfigured_search_error_clean(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_search(query="test")
            text = _all_text_from_result(result)
            assert "error" in text.lower()
            assert OBSIDIAN_TOKEN not in text

    def test_unconfigured_read_error_clean(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_read(path="test/file.md")
            text = _all_text_from_result(result)
            assert "error" in text.lower()
            assert OBSIDIAN_TOKEN not in text

    def test_unconfigured_write_error_clean(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_write(path="test/file.md", content="x")
            text = _all_text_from_result(result)
            assert "error" in text.lower()
            assert OBSIDIAN_TOKEN not in text

    def test_unconfigured_append_error_clean(self) -> None:
        with _unconfigured_obsidian():
            result = obsidian_append(path="test/file.md", content="x")
            text = _all_text_from_result(result)
            assert "error" in text.lower()
            assert OBSIDIAN_TOKEN not in text


# ---------------------------------------------------------------------------
# 7. Server request recording — no token in paths or bodies
# ---------------------------------------------------------------------------


class TestServerRequestRecording:
    """After calling all tools, recorded requests must not contain the token."""

    def test_recorded_requests_clean(self) -> None:
        FakeObsidianHandler.recorded_requests.clear()

        obsidian_search(query="daily")
        obsidian_read(path="journal/2026-02-27.md")
        obsidian_write(path="test/record.md", content="Recording test")
        obsidian_append(path="test/record.md", content="\nMore content")

        for req in FakeObsidianHandler.recorded_requests:
            assert OBSIDIAN_TOKEN not in req["path"], f"Token leaked in request path: {req['path']}"
            assert OBSIDIAN_TOKEN not in req.get("body", ""), f"Token leaked in request body: {req.get('body', '')}"


# ---------------------------------------------------------------------------
# 8. Sanitize edge cases
# ---------------------------------------------------------------------------


class TestSanitizeEdgeCases:
    """Edge cases for the sanitize() function."""

    def test_empty_string(self) -> None:
        assert sanitize("") == ""

    def test_very_long_string(self) -> None:
        long_text = "a" * 1_000_000
        result = sanitize(long_text)
        assert len(result) == 1_000_000

    def test_unicode_preserved(self) -> None:
        text = "日本語テスト 🔐 données sensibles Ü"
        assert sanitize(text) == text

    def test_nested_json_with_credential(self) -> None:
        nested = json.dumps(
            {
                "data": {
                    "auth": f"Bearer {OBSIDIAN_TOKEN}",
                    "safe": "no secrets here",
                }
            }
        )
        result = sanitize(nested)
        assert OBSIDIAN_TOKEN not in result
        assert "[REDACTED]" in result
        assert "no secrets here" in result

    def test_multiline_auth_headers(self) -> None:
        text = (
            "Line 1: normal text\n"
            f"Authorization: Bearer {OBSIDIAN_TOKEN}\n"
            "Line 3: more normal text\n"
            f"Cookie: session={HA_TOKEN}\n"
            "Line 5: final line"
        )
        result = sanitize(text)
        assert OBSIDIAN_TOKEN not in result
        assert HA_TOKEN not in result
        assert "Line 1: normal text" in result
        assert "Line 5: final line" in result


# ---------------------------------------------------------------------------
# 9. Cross-tool credential isolation
# ---------------------------------------------------------------------------


class TestCrossToolCredentialIsolation:
    """Credentials must not leak across tool boundaries."""

    def test_ha_outputs_do_not_contain_obsidian_token(self) -> None:
        result1 = ha_list_entities()
        result2 = ha_get_state(entity_id="light.living_room")
        text = _all_text_from_result(result1) + " " + _all_text_from_result(result2)
        assert OBSIDIAN_TOKEN not in text

    def test_obsidian_outputs_do_not_contain_ha_token(self) -> None:
        result1 = obsidian_search(query="daily")
        result2 = obsidian_read(path="journal/2026-02-27.md")
        text = _all_text_from_result(result1) + " " + _all_text_from_result(result2)
        assert HA_TOKEN not in text

    def test_ha_error_does_not_contain_obsidian_token(self) -> None:
        """Even HA errors must not reveal the Obsidian token."""
        result = ha_get_state(entity_id="nonexistent.entity_xyz")
        text = _all_text_from_result(result)
        assert OBSIDIAN_TOKEN not in text

    def test_obsidian_error_does_not_contain_ha_token(self) -> None:
        """Even Obsidian errors must not reveal the HA token."""
        result = obsidian_read(path="nonexistent/note.md")
        text = _all_text_from_result(result)
        assert HA_TOKEN not in text
