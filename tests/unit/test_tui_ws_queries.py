"""Behavioral tests for WebSocketGateway REST-backed query methods.

Tests exercise real WebSocketGateway instances against real (or unreachable)
HTTP endpoints.  NO mocks, NO monkeypatch -- per project policy.
"""

import asyncio

import pytest

from corvus.tui.protocol.base import SessionDetail, SessionSummary
from corvus.tui.protocol.websocket import WebSocketGateway


# ---------------------------------------------------------------------------
# _rest_base_url derivation
# ---------------------------------------------------------------------------

class TestRestBaseUrl:
    """Verify base_http_url is derived correctly from various WS URLs."""

    def test_ws_localhost_with_path(self) -> None:
        gw = WebSocketGateway("ws://localhost:8000/ws")
        assert gw.base_http_url == "http://localhost:8000"

    def test_ws_localhost_no_path(self) -> None:
        gw = WebSocketGateway("ws://localhost:8000")
        assert gw.base_http_url == "http://localhost:8000"

    def test_wss_becomes_https(self) -> None:
        gw = WebSocketGateway("wss://corvus.example.com/ws")
        assert gw.base_http_url == "https://corvus.example.com"

    def test_wss_with_port(self) -> None:
        gw = WebSocketGateway("wss://host.local:9443/ws/chat")
        assert gw.base_http_url == "https://host.local:9443"

    def test_ws_ip_address(self) -> None:
        gw = WebSocketGateway("ws://192.168.1.100:8000/ws")
        assert gw.base_http_url == "http://192.168.1.100:8000"

    def test_bare_host_no_scheme(self) -> None:
        gw = WebSocketGateway("localhost:8000/ws")
        assert gw.base_http_url == "http://localhost:8000"


# ---------------------------------------------------------------------------
# _auth_headers
# ---------------------------------------------------------------------------

class TestAuthHeaders:
    """Verify auth header generation with and without a token."""

    def test_headers_with_token(self) -> None:
        gw = WebSocketGateway("ws://localhost:8000/ws", token="secret-abc")
        assert gw._auth_headers == {"Authorization": "Bearer secret-abc"}

    def test_headers_without_token(self) -> None:
        gw = WebSocketGateway("ws://localhost:8000/ws")
        assert gw._auth_headers == {}

    def test_headers_none_token(self) -> None:
        gw = WebSocketGateway("ws://localhost:8000/ws", token=None)
        assert gw._auth_headers == {}

    def test_headers_after_set_token(self) -> None:
        gw = WebSocketGateway("ws://localhost:8000/ws")
        assert gw._auth_headers == {}
        gw.set_token("new-token")
        assert gw._auth_headers == {"Authorization": "Bearer new-token"}


# ---------------------------------------------------------------------------
# Graceful error handling -- unreachable endpoint
# ---------------------------------------------------------------------------

# Use port 1 which is almost certainly unreachable / refused.
UNREACHABLE_URL = "ws://localhost:1/ws"


class TestConnectionErrorGrace:
    """All query methods must return safe defaults when the server is unreachable."""

    @pytest.fixture()
    def gw(self) -> WebSocketGateway:
        return WebSocketGateway(UNREACHABLE_URL, token="test-token")

    @pytest.mark.asyncio()
    async def test_list_sessions_returns_empty(self, gw: WebSocketGateway) -> None:
        result = await gw.list_sessions()
        assert result == []

    @pytest.mark.asyncio()
    async def test_resume_session_returns_stub(self, gw: WebSocketGateway) -> None:
        result = await gw.resume_session("nonexistent-id")
        assert isinstance(result, SessionDetail)
        assert result.session_id == "nonexistent-id"

    @pytest.mark.asyncio()
    async def test_list_agent_tools_returns_empty(self, gw: WebSocketGateway) -> None:
        result = await gw.list_agent_tools("work")
        assert result == []

    @pytest.mark.asyncio()
    async def test_list_models_falls_back_to_cache(self, gw: WebSocketGateway) -> None:
        gw._cached_models = [{"id": "cached-model"}]
        result = await gw.list_models()
        assert result == [{"id": "cached-model"}]

    @pytest.mark.asyncio()
    async def test_memory_search_returns_empty(self, gw: WebSocketGateway) -> None:
        result = await gw.memory_search("hello", "personal")
        assert result == []

    @pytest.mark.asyncio()
    async def test_memory_list_returns_empty(self, gw: WebSocketGateway) -> None:
        result = await gw.memory_list("personal")
        assert result == []

    @pytest.mark.asyncio()
    async def test_memory_save_returns_empty_string(self, gw: WebSocketGateway) -> None:
        result = await gw.memory_save("remember this", "personal")
        assert result == ""

    @pytest.mark.asyncio()
    async def test_memory_forget_returns_false(self, gw: WebSocketGateway) -> None:
        result = await gw.memory_forget("some-id", "personal")
        assert result is False


# ---------------------------------------------------------------------------
# REST helper internals
# ---------------------------------------------------------------------------

class TestRestHelpers:
    """Verify internal REST helper behavior."""

    @pytest.mark.asyncio()
    async def test_rest_get_returns_none_on_error(self) -> None:
        gw = WebSocketGateway(UNREACHABLE_URL)
        result = await gw._rest_get("/api/sessions")
        assert result is None

    @pytest.mark.asyncio()
    async def test_rest_post_returns_none_on_error(self) -> None:
        gw = WebSocketGateway(UNREACHABLE_URL)
        result = await gw._rest_post("/api/memory", {"text": "hi", "agent": "x"})
        assert result is None

    @pytest.mark.asyncio()
    async def test_rest_delete_returns_none_on_error(self) -> None:
        gw = WebSocketGateway(UNREACHABLE_URL)
        result = await gw._rest_delete("/api/memory/abc")
        assert result is None
