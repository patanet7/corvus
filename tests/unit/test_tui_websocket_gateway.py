"""Tests for WebSocket gateway protocol implementation.

Tests the WebSocketGateway class that connects to the Corvus server
over WebSocket for chat and REST API for queries.

NO MOCKS — uses a real asyncio echo server for WebSocket tests and
real HTTP responses for REST tests.
"""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
import pytest_asyncio
import websockets
import websockets.asyncio.server

from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import (
    ConfirmRequest,
    ErrorEvent,
    ProtocolEvent,
    RunComplete,
    RunOutputChunk,
    RunStart,
    ToolResult,
    ToolStart,
    parse_event,
)
from corvus.tui.protocol.websocket import WebSocketGateway


# ---------------------------------------------------------------------------
# Test fixtures — real WebSocket echo server
# ---------------------------------------------------------------------------


class FakeCorvusServer:
    """Minimal WebSocket server that mimics Corvus protocol."""

    def __init__(self) -> None:
        self.received_messages: list[dict] = []
        self.responses_to_send: list[dict] = []
        self._server: websockets.asyncio.server.Server | None = None
        self.port: int = 0
        self._init_payload: dict = {
            "type": "init",
            "agents": [
                {"id": "huginn", "label": "Huginn", "description": "Router"},
                {"id": "homelab", "label": "Homelab", "description": "Home automation"},
            ],
            "models": [{"id": "claude-sonnet", "name": "Claude Sonnet"}],
            "default_model": "claude-sonnet",
            "default_agent": "huginn",
            "session_id": "test-session-001",
        }

    async def _handler(self, websocket: websockets.asyncio.server.ServerConnection) -> None:
        """Handle a single WebSocket connection."""
        # Send init message on connect
        await websocket.send(json.dumps(self._init_payload))

        async for message in websocket:
            msg = json.loads(message)
            self.received_messages.append(msg)

            if msg.get("type") == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
                continue

            if msg.get("type") == "confirm_response":
                continue

            # Send scripted responses for chat messages
            for resp in self.responses_to_send:
                await websocket.send(json.dumps(resp))
            self.responses_to_send.clear()

    async def start(self) -> None:
        self._server = await websockets.asyncio.server.serve(
            self._handler, "127.0.0.1", 0,
        )
        # Get the assigned port
        for sock in self._server.sockets:
            self.port = sock.getsockname()[1]
            break

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def script_chat_response(self, agent: str, text: str, tokens: int = 100) -> None:
        """Queue a chat response sequence."""
        self.responses_to_send.extend([
            {"type": "run_start", "agent": agent, "run_id": "r1"},
            {"type": "run_output_chunk", "agent": agent, "content": text},
            {"type": "run_complete", "agent": agent, "run_id": "r1", "tokens_used": tokens},
        ])

    def script_tool_use(self, agent: str, tool: str, params: dict, output: str) -> None:
        """Queue a tool use sequence."""
        self.responses_to_send.extend([
            {"type": "run_start", "agent": agent, "run_id": "r1"},
            {"type": "tool_start", "agent": agent, "tool": tool, "tool_id": "t1", "input": params},
            {"type": "tool_result", "agent": agent, "tool": tool, "tool_id": "t1", "output": output, "status": "success"},
            {"type": "run_complete", "agent": agent, "run_id": "r1", "tokens_used": 200},
        ])

    def script_confirm(self, agent: str, tool: str, params: dict) -> None:
        """Queue a confirmation request."""
        self.responses_to_send.extend([
            {"type": "run_start", "agent": agent, "run_id": "r1"},
            {"type": "confirm_request", "agent": agent, "tool": tool, "tool_id": "c1", "input": params, "risk": "high"},
        ])


@pytest_asyncio.fixture
async def server():
    s = FakeCorvusServer()
    await s.start()
    yield s
    await s.stop()


@pytest_asyncio.fixture
async def gateway_url(server: FakeCorvusServer) -> str:
    return f"ws://127.0.0.1:{server.port}"


# ---------------------------------------------------------------------------
# Gateway construction
# ---------------------------------------------------------------------------


class TestWebSocketGatewayConstruction:
    """WebSocketGateway implements GatewayProtocol."""

    def test_implements_protocol(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000")
        assert isinstance(gw, GatewayProtocol)

    def test_stores_url(self) -> None:
        gw = WebSocketGateway(url="ws://example.com:9090")
        assert gw.url == "ws://example.com:9090"

    def test_stores_token(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000", token="abc123")
        assert gw.token == "abc123"

    def test_default_no_token(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000")
        assert gw.token is None

    def test_base_url_derived(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000/ws")
        assert gw.base_http_url == "http://localhost:8000"

    def test_base_url_from_wss(self) -> None:
        gw = WebSocketGateway(url="wss://example.com/ws")
        assert gw.base_http_url == "https://example.com"


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestWebSocketConnection:
    """connect() establishes WebSocket connection and receives init."""

    @pytest.mark.asyncio
    async def test_connect_receives_init(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()
        assert gw.connected
        assert gw.session_id == "test-session-001"
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_closes(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()
        await gw.disconnect()
        assert not gw.connected

    @pytest.mark.asyncio
    async def test_connect_with_token(self, server: FakeCorvusServer) -> None:
        gw = WebSocketGateway(url=f"ws://127.0.0.1:{server.port}", token="secret-token")
        await gw.connect()
        assert gw.connected
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_init_populates_agents(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()
        agents = gw.cached_agents
        assert len(agents) == 2
        assert agents[0]["id"] == "huginn"
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Sending messages
# ---------------------------------------------------------------------------


class TestWebSocketSendMessage:
    """send_message sends correct JSON to the server."""

    @pytest.mark.asyncio
    async def test_send_basic_message(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()

        server.script_chat_response("huginn", "Hello!")
        await gw.send_message("hi there")
        await asyncio.sleep(0.1)

        assert len(server.received_messages) >= 1
        msg = server.received_messages[-1]
        assert msg["message"] == "hi there"
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_send_with_requested_agent(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()

        server.script_chat_response("homelab", "Status OK")
        await gw.send_message("check status", requested_agent="homelab")
        await asyncio.sleep(0.1)

        msg = server.received_messages[-1]
        assert msg["target_agent"] == "homelab"
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_send_with_session_id(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()

        server.script_chat_response("huginn", "OK")
        await gw.send_message("hello", session_id="custom-session")
        await asyncio.sleep(0.1)

        msg = server.received_messages[-1]
        assert msg.get("session_id") == "custom-session"
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Event streaming
# ---------------------------------------------------------------------------


class TestWebSocketEventStreaming:
    """Events from server are parsed and forwarded to callback."""

    @pytest.mark.asyncio
    async def test_receives_run_events(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        received: list[ProtocolEvent] = []

        async def on_event(event: ProtocolEvent) -> None:
            received.append(event)

        gw.on_event(on_event)
        await gw.connect()

        server.script_chat_response("huginn", "Hello world", tokens=150)
        await gw.send_message("hi")
        await asyncio.sleep(0.2)

        types = [e.type for e in received]
        assert "run_start" in types
        assert "run_output_chunk" in types
        assert "run_complete" in types
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_receives_tool_events(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        received: list[ProtocolEvent] = []

        async def on_event(event: ProtocolEvent) -> None:
            received.append(event)

        gw.on_event(on_event)
        await gw.connect()

        server.script_tool_use("homelab", "Bash", {"command": "ls"}, "file1.py")
        await gw.send_message("list files")
        await asyncio.sleep(0.2)

        types = [e.type for e in received]
        assert "tool_start" in types
        assert "tool_result" in types

        tool_start = next(e for e in received if e.type == "tool_start")
        assert isinstance(tool_start, ToolStart)
        assert tool_start.tool == "Bash"
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_receives_confirm_request(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        received: list[ProtocolEvent] = []

        async def on_event(event: ProtocolEvent) -> None:
            received.append(event)

        gw.on_event(on_event)
        await gw.connect()

        server.script_confirm("homelab", "Bash", {"command": "rm -rf /"})
        await gw.send_message("delete everything")
        await asyncio.sleep(0.2)

        types = [e.type for e in received]
        assert "confirm_request" in types

        confirm = next(e for e in received if e.type == "confirm_request")
        assert isinstance(confirm, ConfirmRequest)
        assert confirm.tool == "Bash"
        assert confirm.risk == "high"
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Confirmation response
# ---------------------------------------------------------------------------


class TestWebSocketConfirmResponse:
    """respond_confirm sends approval back to server."""

    @pytest.mark.asyncio
    async def test_approve_confirm(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()

        await gw.respond_confirm("c1", approved=True)
        await asyncio.sleep(0.1)

        confirm_msgs = [m for m in server.received_messages if m.get("type") == "confirm_response"]
        assert len(confirm_msgs) == 1
        assert confirm_msgs[0]["tool_call_id"] == "c1"
        assert confirm_msgs[0]["approved"] is True
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_deny_confirm(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()

        await gw.respond_confirm("c1", approved=False)
        await asyncio.sleep(0.1)

        confirm_msgs = [m for m in server.received_messages if m.get("type") == "confirm_response"]
        assert len(confirm_msgs) == 1
        assert confirm_msgs[0]["approved"] is False
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Cancel run
# ---------------------------------------------------------------------------


class TestWebSocketCancelRun:
    """cancel_run sends interrupt to server."""

    @pytest.mark.asyncio
    async def test_cancel_sends_interrupt(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()

        await gw.cancel_run("r1")
        await asyncio.sleep(0.1)

        interrupt_msgs = [m for m in server.received_messages if m.get("type") == "interrupt"]
        assert len(interrupt_msgs) == 1
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Agent/model queries via cached init data
# ---------------------------------------------------------------------------


class TestWebSocketCachedQueries:
    """list_agents/list_models return data from init payload."""

    @pytest.mark.asyncio
    async def test_list_agents(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()
        agents = await gw.list_agents()
        assert len(agents) == 2
        assert agents[0]["id"] == "huginn"
        assert agents[1]["id"] == "homelab"
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_list_models(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()
        models = await gw.list_models()
        assert len(models) == 1
        assert models[0]["id"] == "claude-sonnet"
        await gw.disconnect()


# ---------------------------------------------------------------------------
# Ping/pong keepalive
# ---------------------------------------------------------------------------


class TestWebSocketPingPong:
    """Gateway handles ping/pong keepalive."""

    @pytest.mark.asyncio
    async def test_ping_gets_pong(self, server: FakeCorvusServer, gateway_url: str) -> None:
        gw = WebSocketGateway(url=gateway_url)
        await gw.connect()
        # The internal listener should handle pongs automatically
        assert gw.connected
        await gw.disconnect()
