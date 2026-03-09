"""WebSocket-based gateway protocol for the Corvus TUI.

Connects to a running Corvus server over WebSocket for chat and events.
Uses the same GatewayProtocol interface as InProcessGateway so the TUI
remains transport-agnostic.

Protocol:
  - Server sends {"type": "init", ...} on connect with agents, models, session_id
  - Client sends {"message": "...", "target_agent": "..."} for chat
  - Client sends {"type": "confirm_response", ...} for tool confirmations
  - Client sends {"type": "interrupt"} to cancel runs
  - Client sends {"type": "ping"} for keepalive, server responds {"type": "pong"}
  - Server streams events: run_start, run_output_chunk, run_complete,
    tool_start, tool_result, confirm_request, error, etc.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets
import websockets.asyncio.client

from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event

logger = logging.getLogger("corvus.tui.websocket")


class WebSocketGateway(GatewayProtocol):
    """Gateway that connects to a Corvus server over WebSocket.

    Parameters
    ----------
    url:
        WebSocket URL, e.g. ``ws://localhost:8000/ws`` or ``ws://localhost:8000``.
    token:
        Optional session token for authentication (sent as ``?token=`` query param).
    """

    def __init__(self, url: str, token: str | None = None) -> None:
        self._url = url
        self._token = token
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._event_callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]] | None = None
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        self._session_id: str = ""

        # Cached data from init payload
        self._cached_agents: list[dict[str, Any]] = []
        self._cached_models: list[dict[str, Any]] = []

    # -- Properties --

    @property
    def url(self) -> str:
        return self._url

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def cached_agents(self) -> list[dict[str, Any]]:
        return self._cached_agents

    @property
    def base_http_url(self) -> str:
        """Derive HTTP base URL from WebSocket URL."""
        url = self._url
        # Strip path
        if "://" in url:
            scheme, rest = url.split("://", 1)
            host = rest.split("/", 1)[0]
        else:
            scheme = "ws"
            host = url.split("/", 1)[0]

        http_scheme = "https" if scheme == "wss" else "http"
        return f"{http_scheme}://{host}"

    # -- Connection lifecycle --

    async def connect(self) -> None:
        """Connect to the Corvus server WebSocket endpoint."""
        connect_url = self._url
        if self._token:
            sep = "&" if "?" in connect_url else "?"
            connect_url = f"{connect_url}{sep}token={self._token}"

        self._ws = await websockets.asyncio.client.connect(connect_url)
        self._connected = True

        # Read the init message
        raw = await self._ws.recv()
        init_data = json.loads(raw)
        if init_data.get("type") == "init":
            self._session_id = init_data.get("session_id", "")
            self._cached_agents = init_data.get("agents", [])
            self._cached_models = init_data.get("models", [])

        # Start background listener for server events
        self._listener_task = asyncio.create_task(self._listen())

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

    # -- Background listener --

    async def _listen(self) -> None:
        """Background task: read messages from WebSocket and dispatch events."""
        assert self._ws is not None
        try:
            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message from server")
                    continue

                msg_type = data.get("type", "")

                # Skip pong responses
                if msg_type == "pong":
                    continue

                # Parse and dispatch event
                if self._event_callback:
                    event = parse_event(data)
                    await self._event_callback(event)

        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
            self._connected = False
        except asyncio.CancelledError:
            pass

    # -- Messaging --

    async def send_message(
        self,
        text: str,
        *,
        session_id: str | None = None,
        requested_agent: str | None = None,
    ) -> None:
        """Send a chat message to the server."""
        assert self._ws is not None, "connect() must be called before send_message()"
        payload: dict[str, Any] = {"message": text}
        if session_id:
            payload["session_id"] = session_id
        if requested_agent:
            payload["target_agent"] = requested_agent
        await self._ws.send(json.dumps(payload))

    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        """Send a confirmation response back to the server."""
        assert self._ws is not None, "connect() must be called before respond_confirm()"
        await self._ws.send(json.dumps({
            "type": "confirm_response",
            "tool_call_id": tool_id,
            "approved": approved,
        }))

    async def cancel_run(self, run_id: str) -> None:
        """Send an interrupt signal to cancel the current run."""
        assert self._ws is not None, "connect() must be called before cancel_run()"
        await self._ws.send(json.dumps({"type": "interrupt"}))

    # -- Queries (from cached init data) --

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return agents from the init payload."""
        return self._cached_agents

    async def list_models(self) -> list[dict[str, Any]]:
        """Return models from the init payload."""
        return self._cached_models

    # -- Session operations (not yet backed by REST) --

    async def list_sessions(self) -> list[SessionSummary]:
        """List sessions. Not yet implemented for WebSocket mode."""
        return []

    async def resume_session(self, session_id: str) -> SessionDetail:
        """Resume a session. Not yet implemented for WebSocket mode."""
        return SessionDetail(session_id=session_id)

    # -- Memory operations (not yet backed by REST) --

    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories. Not yet implemented for WebSocket mode."""
        return []

    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """List memories. Not yet implemented for WebSocket mode."""
        return []

    async def memory_save(self, content: str, agent_name: str) -> str:
        """Save a memory. Not yet implemented for WebSocket mode."""
        return ""

    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        """Forget a memory. Not yet implemented for WebSocket mode."""
        return False

    # -- Tool queries --

    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        """List tools for an agent. Not yet implemented for WebSocket mode."""
        return []

    # -- Event registration --

    def on_event(
        self,
        callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an async callback to receive protocol events."""
        self._event_callback = callback
