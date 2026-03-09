"""Tests for /login command in the Corvus TUI.

Tests the login flow for WebSocket authentication including:
- /login in non-websocket mode shows appropriate message
- /login sets pending flag when no token argument given
- /login with token argument stores token and reconnects
- WebSocketGateway.set_token stores the token
- Pending login properties and clear methods

NO MOCKS — uses real instances with StringIO-backed Console for output capture.
"""

import asyncio
import io
import json

import pytest
import pytest_asyncio
import websockets
import websockets.asyncio.server
from rich.console import Console

from corvus.tui.commands.builtins import SystemCommandHandler
from corvus.tui.commands.registry import CommandRegistry, InputTier
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.split_manager import SplitManager
from corvus.tui.input.completer import ChatCompleter
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.protocol.websocket import WebSocketGateway
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Helpers — real Console capturing output to a StringIO buffer
# ---------------------------------------------------------------------------


def _make_handler(gateway=None) -> tuple[SystemCommandHandler, io.StringIO]:
    """Build a real SystemCommandHandler with captured console output."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console, theme)
    agent_stack = AgentStack()
    registry = CommandRegistry()
    parser = InputParser()
    completer = ChatCompleter(registry)
    split_manager = SplitManager()
    status_bar = StatusBar(agent_stack, TokenCounter(), theme)
    token_counter = TokenCounter()

    handler = SystemCommandHandler(
        renderer=renderer,
        agent_stack=agent_stack,
        command_registry=registry,
        gateway=gateway or InProcessGateway(),
        parser=parser,
        completer=completer,
        split_manager=split_manager,
        status_bar=status_bar,
        token_counter=token_counter,
    )
    handler.theme = theme
    handler.console = console
    return handler, buf


# ---------------------------------------------------------------------------
# Fake Corvus server for reconnection tests
# ---------------------------------------------------------------------------


class FakeCorvusServer:
    """Minimal WebSocket server that mimics Corvus init handshake."""

    def __init__(self) -> None:
        self._server: websockets.asyncio.server.Server | None = None
        self.port: int = 0
        self.connection_count: int = 0

    async def _handler(self, websocket: websockets.asyncio.server.ServerConnection) -> None:
        self.connection_count += 1
        await websocket.send(json.dumps({
            "type": "init",
            "agents": [{"id": "huginn", "label": "Huginn"}],
            "models": [],
            "session_id": f"session-{self.connection_count}",
        }))
        try:
            async for _ in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass

    async def start(self) -> None:
        self._server = await websockets.asyncio.server.serve(
            self._handler, "127.0.0.1", 0,
        )
        for sock in self._server.sockets:
            self.port = sock.getsockname()[1]
            break

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest_asyncio.fixture
async def fake_server():
    s = FakeCorvusServer()
    await s.start()
    yield s
    await s.stop()


# ---------------------------------------------------------------------------
# WebSocketGateway.set_token
# ---------------------------------------------------------------------------


class TestWebSocketGatewaySetToken:
    """set_token stores the token on the gateway instance."""

    def test_set_token_stores_value(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000")
        assert gw.token is None
        gw.set_token("my-secret-token")
        assert gw.token == "my-secret-token"

    def test_set_token_overwrites_previous(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000", token="old-token")
        assert gw.token == "old-token"
        gw.set_token("new-token")
        assert gw.token == "new-token"

    def test_set_token_does_not_connect(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:8000")
        gw.set_token("token")
        assert not gw.connected


# ---------------------------------------------------------------------------
# /login in non-websocket (in-process) mode
# ---------------------------------------------------------------------------


class TestLoginNonWebSocket:
    """/login shows 'not needed' when using InProcessGateway."""

    @pytest.mark.asyncio
    async def test_login_inprocess_shows_not_needed(self) -> None:
        handler, buf = _make_handler(gateway=InProcessGateway())
        parsed = ParsedInput(raw="/login", text="/login", kind="command", command="login")
        result = await handler.handle(parsed)
        assert result is True
        output = buf.getvalue()
        assert "not needed" in output.lower() or "in-process" in output.lower()

    @pytest.mark.asyncio
    async def test_login_inprocess_does_not_set_pending(self) -> None:
        handler, _ = _make_handler(gateway=InProcessGateway())
        parsed = ParsedInput(raw="/login", text="/login", kind="command", command="login")
        await handler.handle(parsed)
        assert handler.pending_login is False


# ---------------------------------------------------------------------------
# /login in websocket mode — pending flow
# ---------------------------------------------------------------------------


class TestLoginPendingFlag:
    """/login without args sets pending flag and prompts for token."""

    @pytest.mark.asyncio
    async def test_login_no_args_sets_pending(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:9999")
        handler, buf = _make_handler(gateway=gw)
        parsed = ParsedInput(raw="/login", text="/login", kind="command", command="login")
        result = await handler.handle(parsed)
        assert result is True
        assert handler.pending_login is True
        output = buf.getvalue()
        assert "token" in output.lower()

    def test_clear_pending_login(self) -> None:
        gw = WebSocketGateway(url="ws://localhost:9999")
        handler, _ = _make_handler(gateway=gw)
        handler._pending_login = True
        assert handler.pending_login is True
        handler.clear_pending_login()
        assert handler.pending_login is False

    def test_pending_login_default_false(self) -> None:
        handler, _ = _make_handler()
        assert handler.pending_login is False


# ---------------------------------------------------------------------------
# /login with token — reconnection against real server
# ---------------------------------------------------------------------------


class TestLoginWithToken:
    """/login <token> stores token and reconnects."""

    @pytest.mark.asyncio
    async def test_login_with_token_reconnects(self, fake_server: FakeCorvusServer) -> None:
        url = f"ws://127.0.0.1:{fake_server.port}"
        gw = WebSocketGateway(url=url)
        await gw.connect()
        assert fake_server.connection_count == 1
        assert gw.session_id == "session-1"

        handler, buf = _make_handler(gateway=gw)
        parsed = ParsedInput(
            raw="/login new-secret-token",
            text="/login new-secret-token",
            kind="command",
            command="login",
            command_args="new-secret-token",
        )
        result = await handler.handle(parsed)
        assert result is True
        assert gw.token == "new-secret-token"

        # Should have reconnected (connection count increased)
        assert fake_server.connection_count == 2
        assert gw.session_id == "session-2"
        assert gw.connected

        output = buf.getvalue()
        assert "reconnect" in output.lower()
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_complete_login_stores_and_reconnects(self, fake_server: FakeCorvusServer) -> None:
        url = f"ws://127.0.0.1:{fake_server.port}"
        gw = WebSocketGateway(url=url)
        await gw.connect()

        handler, buf = _make_handler(gateway=gw)
        handler._pending_login = True

        await handler.complete_login("completed-token")
        assert handler.pending_login is False
        assert gw.token == "completed-token"
        assert fake_server.connection_count == 2
        await gw.disconnect()

    @pytest.mark.asyncio
    async def test_login_reconnect_failure_shows_error(self) -> None:
        # Use a port that nothing listens on
        gw = WebSocketGateway(url="ws://127.0.0.1:1")
        handler, buf = _make_handler(gateway=gw)

        parsed = ParsedInput(
            raw="/login bad-token",
            text="/login bad-token",
            kind="command",
            command="login",
            command_args="bad-token",
        )
        result = await handler.handle(parsed)
        assert result is True
        output = buf.getvalue()
        # Should show the reconnection failure
        assert "failed" in output.lower() or "error" in output.lower()
