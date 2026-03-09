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
from datetime import datetime
from typing import Any

import httpx
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

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Return Authorization header dict when a token is available."""
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    # -- REST helpers --

    async def _rest_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform an authenticated GET request against the REST API.

        Returns the parsed JSON response, or ``None`` on error.
        """
        url = f"{self.base_http_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self._auth_headers, params=params)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            logger.warning("REST GET %s failed: %s", url, exc)
            return None

    async def _rest_post(self, path: str, body: dict[str, Any]) -> Any:
        """Perform an authenticated POST request against the REST API.

        Returns the parsed JSON response, or ``None`` on error.
        """
        url = f"{self.base_http_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=self._auth_headers, json=body)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            logger.warning("REST POST %s failed: %s", url, exc)
            return None

    async def _rest_delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform an authenticated DELETE request against the REST API.

        Returns the parsed JSON response, or ``None`` on error.
        """
        url = f"{self.base_http_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(url, headers=self._auth_headers, params=params)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            logger.warning("REST DELETE %s failed: %s", url, exc)
            return None

    # -- Connection lifecycle --

    async def connect(self) -> None:
        """Connect to the Corvus server WebSocket endpoint."""
        connect_url = self._url
        extra_headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}

        self._ws = await websockets.asyncio.client.connect(
            connect_url, additional_headers=extra_headers,
        )
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
        if self._ws is None:
            raise RuntimeError("connect() must be called before _listen()")
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
        if self._ws is None:
            raise RuntimeError("connect() must be called before send_message()")
        payload: dict[str, Any] = {"message": text}
        if session_id:
            payload["session_id"] = session_id
        if requested_agent:
            payload["target_agent"] = requested_agent
        await self._ws.send(json.dumps(payload))

    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        """Send a confirmation response back to the server."""
        if self._ws is None:
            raise RuntimeError("connect() must be called before respond_confirm()")
        await self._ws.send(json.dumps({
            "type": "confirm_response",
            "tool_call_id": tool_id,
            "approved": approved,
        }))

    async def cancel_run(self, run_id: str) -> None:
        """Send an interrupt signal to cancel the current run."""
        if self._ws is None:
            raise RuntimeError("connect() must be called before cancel_run()")
        await self._ws.send(json.dumps({"type": "interrupt"}))

    # -- Queries (from cached init data) --

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return agents from the init payload."""
        return self._cached_agents

    async def list_models(self) -> list[dict[str, Any]]:
        """Return models — prefer REST, fall back to cached init payload."""
        data = await self._rest_get("/api/models")
        if data is not None and isinstance(data, list):
            return data
        return self._cached_models

    # -- Session operations (backed by REST) --

    async def list_sessions(self) -> list[SessionSummary]:
        """List sessions via REST API."""
        data = await self._rest_get("/api/sessions")
        if data is None or not isinstance(data, list):
            return []
        sessions: list[SessionSummary] = []
        for item in data:
            started_at = None
            if item.get("started_at"):
                try:
                    started_at = datetime.fromisoformat(item["started_at"])
                except (ValueError, TypeError):
                    pass
            sessions.append(SessionSummary(
                session_id=item.get("session_id", ""),
                agent_name=item.get("agent_name", ""),
                summary=item.get("summary", ""),
                started_at=started_at,
                message_count=item.get("message_count", 0),
                agents_used=item.get("agents_used", []),
            ))
        return sessions

    async def resume_session(self, session_id: str) -> SessionDetail:
        """Load full session detail via REST API."""
        data = await self._rest_get(f"/api/sessions/{session_id}")
        if data is None or not isinstance(data, dict):
            return SessionDetail(session_id=session_id)
        started_at = None
        if data.get("started_at"):
            try:
                started_at = datetime.fromisoformat(data["started_at"])
            except (ValueError, TypeError):
                pass
        return SessionDetail(
            session_id=data.get("session_id", session_id),
            agent_name=data.get("agent_name", ""),
            summary=data.get("summary", ""),
            started_at=started_at,
            message_count=data.get("message_count", 0),
            agents_used=data.get("agents_used", []),
            messages=data.get("messages", []),
        )

    # -- Memory operations (backed by REST) --

    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories via REST API."""
        data = await self._rest_get(
            "/api/memory/search",
            params={"q": query, "agent": agent_name, "limit": limit},
        )
        if data is not None and isinstance(data, list):
            return data
        return []

    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """List memories via REST API."""
        data = await self._rest_get(
            "/api/memory",
            params={"agent": agent_name, "limit": limit},
        )
        if data is not None and isinstance(data, list):
            return data
        return []

    async def memory_save(self, content: str, agent_name: str) -> str:
        """Save a memory via REST API. Returns the record ID."""
        data = await self._rest_post(
            "/api/memory",
            body={"text": content, "agent": agent_name},
        )
        if data is not None and isinstance(data, dict):
            return data.get("record_id", data.get("id", ""))
        return ""

    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        """Soft-delete a memory via REST API."""
        data = await self._rest_delete(
            f"/api/memory/{record_id}",
            params={"agent": agent_name},
        )
        if data is not None and isinstance(data, dict):
            return data.get("deleted", False)
        return False

    # -- Tool queries (backed by REST) --

    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        """List tools for an agent via REST API."""
        data = await self._rest_get(f"/api/agents/{agent_name}/tools")
        if data is not None and isinstance(data, list):
            return data
        return []

    # -- Token management --

    def set_token(self, token: str) -> None:
        """Update the authentication token for subsequent connections.

        This stores the new token but does NOT automatically reconnect.
        Call disconnect() then connect() to use the new token.
        """
        self._token = token

    # -- Event registration --

    def on_event(
        self,
        callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an async callback to receive protocol events."""
        self._event_callback = callback
