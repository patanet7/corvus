"""Kimi ACP Bridge Client -- WebSocket client for the Kimi bridge protocol.

Implements the ACP (Agent Communication Protocol) over JSON-RPC 2.0 to
communicate with Kimi's bridge server at wss://www.kimi.com/api-claw/bots/agent-ws.

This module is the MODEL PROVIDER layer for Claw. Kimi K2 is the inference
engine -- when an agent needs to think/reason, it sends the prompt through the
Kimi bridge to K2, and K2's response streams back. It is the equivalent of
calling an LLM API endpoint, but over a persistent WebSocket using ACP/JSON-RPC.

Client mode only: We send requests to Kimi (initialize, session/new, session/prompt)
to use K2 as a model for inference. K2 responds with streaming session/update
notifications containing text, thinking, and tool call requests.

Auth: HTTP headers at WebSocket upgrade time (X-Kimi-Bot-Token + X-Kimi-Claw-Version).
Keepalive: JSON {"type": "ping"} every 15 seconds, plus text ping/pong heartbeats.
Liveness: If no data received for 60 seconds, terminate and reconnect.
Reconnect: Exponential backoff with jitter; stops on auth failure (HTTP 401 / WS 4001).

Usage:
    from corvus.kimi_bridge import KimiBridgeClient

    bridge = KimiBridgeClient(bot_token="...")
    async with bridge:
        caps = await bridge.initialize()
        session = await bridge.create_session()
        async for item in bridge.send_prompt_stream(session.session_id, "Hello"):
            if isinstance(item, SessionUpdate):
                print(item.text, end="", flush=True)
            elif isinstance(item, PromptResult):
                print(f"Done: {item.stop_reason}")
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

import websockets
import websockets.exceptions

logger = logging.getLogger("corvus-gateway.kimi-bridge")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIDGE_URL = "wss://www.kimi.com/api-claw/bots/agent-ws"
CLAW_VERSION = "0.7.4"
PING_INTERVAL_SECONDS = 15
LIVENESS_TIMEOUT_SECONDS = 60
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_PROMPT_TIMEOUT = 120.0

# Reconnect backoff
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 60.0
RECONNECT_JITTER = 0.5

# Reconnect notification: random timer 1-3 minutes before actual reconnect
RECONNECT_NOTIFY_MIN = 60.0
RECONNECT_NOTIFY_MAX = 180.0

# ---------------------------------------------------------------------------
# ACP Error Codes
# ---------------------------------------------------------------------------


class AcpErrorCode(int, Enum):
    """Standard ACP error codes from the Kimi bridge protocol."""

    GATEWAY_UNAVAILABLE = -32001
    GATEWAY_ERROR = -32020
    LIFECYCLE_ERROR = -32021
    PROMPT_TIMEOUT = -32022
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602


# ---------------------------------------------------------------------------
# Stop Reasons
# ---------------------------------------------------------------------------


class StopReason(StrEnum):
    """Reasons a session/prompt can complete."""

    END_TURN = "end_turn"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Session Update Types
# ---------------------------------------------------------------------------


class SessionUpdateType(StrEnum):
    """Types of session/update notifications."""

    USER_MESSAGE_CHUNK = "user_message_chunk"
    AGENT_MESSAGE_CHUNK = "agent_message_chunk"
    AGENT_THOUGHT_CHUNK = "agent_thought_chunk"
    TOOL_CALL = "tool_call"
    TOOL_CALL_UPDATE = "tool_call_update"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class PromptCapabilities:
    """Capabilities related to prompt content types."""

    embedded_context: bool = True
    image: bool = True
    audio: bool = False


@dataclass
class SessionCapabilities:
    """Capabilities related to session management."""

    list: dict[str, Any] = field(default_factory=dict)
    web_ssh: bool = False


@dataclass
class AcpCapabilities:
    """Agent capabilities exchanged during initialize handshake."""

    load_session: bool = True
    prompt_capabilities: PromptCapabilities = field(default_factory=PromptCapabilities)
    session_capabilities: SessionCapabilities = field(default_factory=SessionCapabilities)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire format expected by the ACP protocol."""
        return {
            "loadSession": self.load_session,
            "promptCapabilities": {
                "embeddedContext": self.prompt_capabilities.embedded_context,
                "image": self.prompt_capabilities.image,
                "audio": self.prompt_capabilities.audio,
            },
            "sessionCapabilities": {
                "list": self.session_capabilities.list,
                "web-ssh": self.session_capabilities.web_ssh,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcpCapabilities:
        """Deserialize from the ACP wire format."""
        pc_data = data.get("promptCapabilities", {})
        sc_data = data.get("sessionCapabilities", {})
        return cls(
            load_session=data.get("loadSession", True),
            prompt_capabilities=PromptCapabilities(
                embedded_context=pc_data.get("embeddedContext", True),
                image=pc_data.get("image", True),
                audio=pc_data.get("audio", False),
            ),
            session_capabilities=SessionCapabilities(
                list=sc_data.get("list", {}),
                web_ssh=sc_data.get("web-ssh", False),
            ),
        )


@dataclass
class AgentInfo:
    """Agent identification exchanged during initialize."""

    name: str = "corvus-gateway"
    version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentInfo:
        return cls(name=data.get("name", "unknown"), version=data.get("version", "0.0.0"))


@dataclass
class SessionMode:
    """A session mode definition."""

    id: str
    name: str
    description: str = ""


@dataclass
class SessionInfo:
    """Session metadata returned from session/new or session/load."""

    session_id: str
    available_modes: list[SessionMode] = field(default_factory=list)
    current_mode_id: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "modes": {
                "availableModes": [
                    {"id": m.id, "name": m.name, "description": m.description} for m in self.available_modes
                ],
                "currentModeId": self.current_mode_id,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionInfo:
        modes_data = data.get("modes", {})
        available = modes_data.get("availableModes", [])
        return cls(
            session_id=data.get("sessionId", "unknown"),
            available_modes=[
                SessionMode(
                    id=m.get("id", ""),
                    name=m.get("name", ""),
                    description=m.get("description", ""),
                )
                for m in available
            ],
            current_mode_id=modes_data.get("currentModeId", "default"),
        )


@dataclass
class PromptBlock:
    """A content block within a prompt or update.

    Types: text, image, file, resource_link, resource.
    """

    type: str
    text: str = ""
    # Image-specific
    source: str = ""
    media_type: str = ""
    # File-specific
    filename: str = ""
    url: str = ""
    # Resource-specific
    uri: str = ""
    mime_type: str = ""
    # Raw data for unknown or complex block types
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to wire format."""
        result: dict[str, Any] = {"type": self.type}
        if self.type == "text":
            result["text"] = self.text
        elif self.type == "image":
            result["source"] = self.source
            if self.media_type:
                result["mediaType"] = self.media_type
        elif self.type == "file":
            result["filename"] = self.filename
            if self.url:
                result["url"] = self.url
        elif self.type in ("resource_link", "resource"):
            result["uri"] = self.uri
            if self.mime_type:
                result["mimeType"] = self.mime_type
            if self.text:
                result["text"] = self.text
        # Merge any raw fields not covered above
        for k, v in self.raw.items():
            if k not in result:
                result[k] = v
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptBlock:
        block_type = data.get("type", "text")
        return cls(
            type=block_type,
            text=data.get("text", ""),
            source=data.get("source", ""),
            media_type=data.get("mediaType", ""),
            filename=data.get("filename", ""),
            url=data.get("url", ""),
            uri=data.get("uri", ""),
            mime_type=data.get("mimeType", ""),
            raw=data,
        )


@dataclass
class SessionUpdate:
    """A streaming session/update notification."""

    session_id: str
    update_type: str  # SessionUpdateType value
    content: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    # Tool-call specific fields
    tool_call_id: str = ""
    title: str = ""
    status: str = ""

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> SessionUpdate:
        """Parse from session/update notification params."""
        update = params.get("update", {})
        content = update.get("content", {})
        return cls(
            session_id=params.get("sessionId", ""),
            update_type=update.get("sessionUpdate", "unknown"),
            content=content,
            meta=params.get("_meta", {}),
            tool_call_id=update.get("toolCallId", ""),
            title=update.get("title", ""),
            status=update.get("status", ""),
        )

    @property
    def text(self) -> str:
        """Extract text content, if any."""
        if isinstance(self.content, dict):
            return str(self.content.get("text", ""))
        return ""

    @property
    def tool_content(self) -> list[dict[str, Any]]:
        """Extract tool content blocks (for tool_call / tool_call_update)."""
        if isinstance(self.content, list):
            return self.content
        return []


@dataclass
class PromptResult:
    """Final result of a session/prompt request."""

    stop_reason: str = "end_turn"
    meta: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_result(cls, data: dict[str, Any]) -> PromptResult:
        return cls(
            stop_reason=data.get("stopReason", "end_turn"),
            meta=data.get("_meta", {}),
            raw=data,
        )


@dataclass
class PromptResponse:
    """Aggregated response from a session/prompt: all streaming updates plus the final result."""

    updates: list[SessionUpdate] = field(default_factory=list)
    result: PromptResult | None = None
    error: dict[str, Any] | None = None

    @property
    def full_text(self) -> str:
        """Concatenate all agent_message_chunk text content."""
        parts = []
        for u in self.updates:
            if u.update_type == SessionUpdateType.AGENT_MESSAGE_CHUNK:
                t = u.text
                if t:
                    parts.append(t)
        return "".join(parts)

    @property
    def thought_text(self) -> str:
        """Concatenate all agent_thought_chunk text content."""
        parts = []
        for u in self.updates:
            if u.update_type == SessionUpdateType.AGENT_THOUGHT_CHUNK:
                t = u.text
                if t:
                    parts.append(t)
        return "".join(parts)

    @property
    def tool_calls(self) -> list[SessionUpdate]:
        """Return all tool_call updates."""
        return [u for u in self.updates if u.update_type == SessionUpdateType.TOOL_CALL]

    @property
    def tool_results(self) -> list[SessionUpdate]:
        """Return all tool_call_update (result) updates."""
        return [u for u in self.updates if u.update_type == SessionUpdateType.TOOL_CALL_UPDATE]


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def extract_prompt_text(prompt: Any) -> str:
    """Extract plain text from various prompt formats.

    Handles:
    - str: returned directly
    - dict with "text": returned directly
    - dict with "content" (str or list of blocks): text blocks concatenated
    - dict with "messages" (list): last message content extracted
    """
    if isinstance(prompt, str):
        return prompt

    if isinstance(prompt, dict):
        # Direct text field
        if "text" in prompt:
            return str(prompt["text"])

        # Content blocks
        content = prompt.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            if parts:
                return "\n".join(parts)

        # Messages array (take last)
        messages = prompt.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                c = last.get("content", "")
                if isinstance(c, str):
                    return c

    return "(empty prompt)"


def build_meta(
    debug_index: int,
    request_id: str,
    message_type: str = "normal",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build a _meta object for outgoing ACP messages.

    Args:
        debug_index: Monotonically increasing sequence number.
        request_id: The request ID this message relates to.
        message_type: Message type (default "normal").
        session_id: Optional session ID to include in meta.
    """
    meta: dict[str, Any] = {
        "_debug_index": debug_index,
        "messageType": message_type,
        "requestId": request_id,
        "timestamp": int(time.time() * 1000),
    }
    if session_id is not None:
        meta["sessionId"] = session_id
    return meta


def build_session_update(
    session_id: str,
    update_type: str,
    content: dict[str, Any] | list[dict[str, Any]],
    request_id: str,
    meta_index: int,
    tool_call_id: str | None = None,
    title: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build a session/update notification message.

    Args:
        session_id: The session this update belongs to.
        update_type: One of the SessionUpdateType values.
        content: The content dict (text/image) or list (tool content blocks).
        request_id: The request ID of the prompt this responds to.
        meta_index: Debug index for the _meta object.
        tool_call_id: Tool call ID (for tool_call / tool_call_update types).
        title: Tool title (for tool_call / tool_call_update types).
        status: Tool status e.g. "in_progress" or "completed".
    """
    update_body: dict[str, Any] = {
        "sessionUpdate": update_type,
        "content": content,
    }

    # Add tool-call fields when present
    if tool_call_id is not None:
        update_body["toolCallId"] = tool_call_id
    if title is not None:
        update_body["title"] = title
    if status is not None:
        update_body["status"] = status

    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": update_body,
            "_meta": build_meta(meta_index, request_id),
        },
    }


def build_result(
    request_id: str,
    result: dict[str, Any] | None,
    session_id: str | None = None,
    meta_index: int | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC result response.

    Args:
        request_id: The request ID being responded to.
        result: The result payload (can be None for empty results).
        session_id: Optional session ID for _meta context.
        meta_index: Optional debug index for _meta.
    """
    # Normalize None to empty dict for _meta injection
    effective_result = result if result is not None else {}

    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": effective_result,
    }
    if meta_index is not None and isinstance(effective_result, dict):
        if "_meta" not in effective_result:
            effective_result["_meta"] = build_meta(meta_index, request_id, session_id=session_id)
    return msg


def build_error(
    request_id: str | None,
    code: int,
    message: str,
    meta_index: int | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC error response.

    Args:
        request_id: The request ID being responded to (None for notifications).
        code: ACP error code (see AcpErrorCode enum).
        message: Human-readable error description.
        meta_index: Optional debug index for _meta.
    """
    error_body: dict[str, Any] = {"code": code, "message": message}
    if meta_index is not None:
        error_body["data"] = {"_meta": build_meta(meta_index, request_id or "")}

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error_body,
    }


# ---------------------------------------------------------------------------
# Type aliases for server-side callbacks
# ---------------------------------------------------------------------------

# Callback signature: async def handler(request_id: str, params: dict, bridge: KimiBridgeClient)
ServerHandler = Callable[[str, dict[str, Any], "KimiBridgeClient"], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# KimiBridgeClient
# ---------------------------------------------------------------------------


class KimiBridgeClient:
    """WebSocket client for the Kimi ACP bridge protocol.

    Handles both client-side requests (we call K2 for inference) and server-side
    handling (Kimi app users send requests to us). Manages keepalive pings,
    liveness monitoring (60s timeout), auto-reconnect with exponential backoff,
    and message routing.

    Args:
        bot_token: The X-Kimi-Bot-Token for authentication.
        bridge_url: WebSocket URL for the bridge (default: production endpoint).
        agent_name: Name reported in initialize (default: "corvus-gateway").
        agent_version: Version reported in initialize (default: "0.1.0").
        capabilities: Agent capabilities to report (default: standard capabilities).
        auto_reconnect: Whether to reconnect on disconnect (default: True).
        on_session_prompt: Callback for incoming session/prompt requests from Kimi users.
        on_session_new: Callback for incoming session/new requests.
        on_session_cancel: Callback for incoming session/cancel requests.
        on_initialize: Callback for incoming initialize requests (overrides default handler).
    """

    def __init__(
        self,
        bot_token: str,
        bridge_url: str = BRIDGE_URL,
        agent_name: str = "corvus-gateway",
        agent_version: str = "0.1.0",
        capabilities: AcpCapabilities | None = None,
        auto_reconnect: bool = True,
        on_session_prompt: ServerHandler | None = None,
        on_session_new: ServerHandler | None = None,
        on_session_cancel: ServerHandler | None = None,
        on_initialize: ServerHandler | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.bridge_url = bridge_url
        self.agent_info = AgentInfo(name=agent_name, version=agent_version)
        self.capabilities = capabilities or AcpCapabilities()
        self.auto_reconnect = auto_reconnect

        # Server-side callbacks
        self._on_session_prompt = on_session_prompt
        self._on_session_new = on_session_new
        self._on_session_cancel = on_session_cancel
        self._on_initialize = on_initialize

        # Connection state
        self._ws: Any = None
        self._connected = False
        self._auth_failed = False
        self._reconnect_count = 0

        # Request tracking
        self._request_seq = 0
        self._meta_index = 0
        self._pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}

        # Streaming updates collected per request_id
        self._streaming_updates: dict[str, list[SessionUpdate]] = {}
        self._streaming_events: dict[str, asyncio.Event] = {}
        self._streaming_queues: dict[str, asyncio.Queue[SessionUpdate | PromptResult | None]] = {}

        # Liveness tracking -- timestamp of last received data
        self._last_data_received: float = 0.0

        # Background tasks
        self._ping_task: asyncio.Task[None] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._liveness_task: asyncio.Task[None] | None = None
        self._reconnect_timer_task: asyncio.Task[None] | None = None

        # Lifecycle
        self._closing = False
        self._connect_event = asyncio.Event()

    # --- Properties ---

    @property
    def connected(self) -> bool:
        """Whether the WebSocket connection is established and authenticated."""
        return self._connected and self._ws is not None

    @property
    def auth_failed(self) -> bool:
        """Whether authentication has permanently failed (HTTP 401 or WS close 4001)."""
        return self._auth_failed

    # --- Meta index tracking ---

    def _next_meta_index(self) -> int:
        """Return and increment the _debug_index sequence."""
        idx = self._meta_index
        self._meta_index += 1
        return idx

    def _next_request_id(self) -> str:
        """Generate the next request ID."""
        self._request_seq += 1
        return f"req_{self._request_seq}"

    # --- Connection Management ---

    async def connect(self) -> None:
        """Connect to the Kimi bridge WebSocket.

        Establishes the WebSocket connection with auth headers, starts the
        keepalive ping loop, liveness monitor, and message listener. If
        auto_reconnect is enabled, will retry on disconnect with exponential
        backoff.

        Raises:
            ConnectionError: If initial connection fails and auto_reconnect is False.
        """
        self._closing = False
        await self._connect_once()

    async def _connect_once(self) -> None:
        """Establish a single WebSocket connection attempt."""
        headers = {
            "X-Kimi-Claw-Version": CLAW_VERSION,
            "X-Kimi-Bot-Token": self.bot_token,
        }

        try:
            logger.info("Connecting to Kimi bridge at %s", self.bridge_url)
            self._ws = await websockets.connect(
                self.bridge_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
            )
            self._connected = True
            self._reconnect_count = 0
            self._last_data_received = time.monotonic()
            self._connect_event.set()
            logger.info("Connected to Kimi bridge successfully")

            # Start background tasks
            self._ping_task = asyncio.create_task(self._keepalive_loop(), name="kimi-ping")
            self._listener_task = asyncio.create_task(self._listener_loop(), name="kimi-listener")
            self._liveness_task = asyncio.create_task(self._liveness_loop(), name="kimi-liveness")

        except websockets.exceptions.InvalidStatus as e:
            status = getattr(e.response, "status_code", 0) or getattr(e.response, "status", 0)
            if status == 401:
                self._auth_failed = True
                logger.error("Kimi bridge auth failed (HTTP 401) -- will not retry")
                raise ConnectionError("Authentication failed (HTTP 401)") from e
            logger.error("Kimi bridge connection failed (HTTP %s)", status)
            if self.auto_reconnect and not self._closing:
                await self._schedule_reconnect()
            else:
                raise ConnectionError(f"Connection failed (HTTP {status})") from e

        except Exception as e:
            logger.error("Kimi bridge connection error: %s", e)
            if self.auto_reconnect and not self._closing:
                await self._schedule_reconnect()
            else:
                raise ConnectionError(f"Connection failed: {e}") from e

    async def disconnect(self) -> None:
        """Gracefully disconnect from the Kimi bridge.

        Cancels background tasks and closes the WebSocket connection.
        Does not trigger auto-reconnect.
        """
        self._closing = True
        self._connected = False
        self._connect_event.clear()

        # Cancel background tasks
        for task in [
            self._ping_task,
            self._listener_task,
            self._liveness_task,
            self._reconnect_timer_task,
        ]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        self._ping_task = None
        self._listener_task = None
        self._liveness_task = None
        self._reconnect_timer_task = None

        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # Fail all pending requests
        for _req_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(ConnectionError("Disconnected"))
        self._pending_requests.clear()

        # Signal completion to any streaming queues
        for _req_id, queue in self._streaming_queues.items():
            try:
                await queue.put(None)
            except Exception:
                pass
        self._streaming_queues.clear()
        self._streaming_updates.clear()
        self._streaming_events.clear()

        logger.info("Disconnected from Kimi bridge")

    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """Wait until the connection is established.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            True if connected, False if timeout.
        """
        try:
            await asyncio.wait_for(self._connect_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    # --- Reconnect logic ---

    async def _schedule_reconnect(self) -> None:
        """Schedule a reconnection with exponential backoff."""
        if self._auth_failed or self._closing:
            return

        self._reconnect_count += 1
        delay = min(
            RECONNECT_BASE_DELAY * (2 ** (self._reconnect_count - 1)),
            RECONNECT_MAX_DELAY,
        )
        jitter = random.uniform(-RECONNECT_JITTER * delay, RECONNECT_JITTER * delay)
        actual_delay = max(0.1, delay + jitter)

        logger.info(
            "Reconnecting to Kimi bridge in %.1fs (attempt %d)",
            actual_delay,
            self._reconnect_count,
        )
        await asyncio.sleep(actual_delay)

        if not self._closing and not self._auth_failed:
            await self._connect_once()

    async def _handle_reconnect_notification(self) -> None:
        """Handle a _kimi.com/reconnect notification.

        The protocol specifies: start a 1-3 minute random timer; if no
        non-pong message arrives in that window, reconnect.
        """
        delay = random.uniform(RECONNECT_NOTIFY_MIN, RECONNECT_NOTIFY_MAX)
        logger.info("Received reconnect notification, will reconnect in %.0fs if idle", delay)

        async def _reconnect_timer() -> None:
            await asyncio.sleep(delay)
            if self._connected and not self._closing:
                logger.info("Reconnect timer expired, initiating reconnect")
                await self._do_reconnect()

        # Cancel any existing reconnect timer
        if self._reconnect_timer_task and not self._reconnect_timer_task.done():
            self._reconnect_timer_task.cancel()
        self._reconnect_timer_task = asyncio.create_task(_reconnect_timer(), name="kimi-reconnect-timer")

    async def _do_reconnect(self) -> None:
        """Force a reconnection: close current connection, then reconnect."""
        self._connected = False
        self._connect_event.clear()

        # Cancel listener/ping/liveness but not the reconnect timer itself
        for task in [self._ping_task, self._listener_task, self._liveness_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        await self._connect_once()

    # --- Keepalive ---

    async def _keepalive_loop(self) -> None:
        """Send JSON ping every PING_INTERVAL_SECONDS."""
        try:
            while self._connected and self._ws:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                if self._ws and self._connected:
                    try:
                        await self._ws.send(json.dumps({"type": "ping"}))
                    except Exception as e:
                        logger.warning("Keepalive ping failed: %s", e)
                        break
        except asyncio.CancelledError:
            pass

    # --- Liveness Monitor ---

    async def _liveness_loop(self) -> None:
        """Check liveness every 5 seconds. If no data for 60s, reconnect.

        Per the ACP protocol: every 5s check, if no data received for 60s,
        terminate and reconnect.
        """
        try:
            while self._connected and not self._closing:
                await asyncio.sleep(5.0)
                if not self._connected or self._closing:
                    break
                elapsed = time.monotonic() - self._last_data_received
                if elapsed >= LIVENESS_TIMEOUT_SECONDS:
                    logger.warning("Liveness timeout: no data for %.0fs, reconnecting", elapsed)
                    await self._do_reconnect()
                    return
        except asyncio.CancelledError:
            pass

    # --- Message Sending ---

    async def _send_raw(self, data: dict[str, Any]) -> None:
        """Send a raw JSON message over the WebSocket.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to Kimi bridge")

        raw = json.dumps(data, ensure_ascii=False)
        await self._ws.send(raw)
        logger.debug("Sent: %s", raw[:500])

    async def _send_rpc_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response.

        Args:
            method: The RPC method name.
            params: Optional parameters.
            timeout: Maximum seconds to wait for response.

        Returns:
            The full JSON-RPC response dict (containing "result" or "error").

        Raises:
            asyncio.TimeoutError: If no response within timeout.
            ConnectionError: If not connected.
        """
        req_id = self._next_request_id()
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_requests[req_id] = future

        await self._send_raw(msg)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except TimeoutError:
            self._pending_requests.pop(req_id, None)
            logger.warning("Request timeout for %s (id=%s)", method, req_id)
            raise

    # --- Client-Side Methods (we send to Kimi for K2 inference) ---

    async def initialize(self) -> dict[str, Any]:
        """Send an initialize request and return the server's capabilities.

        Returns:
            The result dict containing protocolVersion, agentCapabilities, agentInfo.

        Raises:
            asyncio.TimeoutError: If no response within 30 seconds.
            ConnectionError: If not connected.
            RuntimeError: If the server returns an error.
        """
        resp = await self._send_rpc_request(
            "initialize",
            {"protocolVersion": 1},
        )
        if "error" in resp:
            raise RuntimeError(f"Initialize failed: {resp['error']}")
        result: dict[str, Any] = resp.get("result", {})
        return result

    async def create_session(self, cwd: str = ".", meta: dict[str, Any] | None = None) -> SessionInfo:
        """Create a new session on the Kimi bridge.

        Args:
            cwd: Working directory context (default ".").
            meta: Optional _meta fields for the request.

        Returns:
            SessionInfo with the session ID and available modes.

        Raises:
            asyncio.TimeoutError: If no response within 30 seconds.
            ConnectionError: If not connected.
            RuntimeError: If the server returns an error.
        """
        params: dict[str, Any] = {"cwd": cwd}
        if meta:
            params["_meta"] = meta

        resp = await self._send_rpc_request("session/new", params)
        if "error" in resp:
            raise RuntimeError(f"session/new failed: {resp['error']}")
        return SessionInfo.from_dict(resp.get("result", {}))

    async def load_session(self, session_id: str) -> dict[str, Any]:
        """Load an existing session.

        Args:
            session_id: The session ID to load.

        Returns:
            The result dict from the server.

        Raises:
            asyncio.TimeoutError: If no response within 30 seconds.
            ConnectionError: If not connected.
            RuntimeError: If the server returns an error.
        """
        resp = await self._send_rpc_request(
            "session/load",
            {"sessionId": session_id},
        )
        if "error" in resp:
            raise RuntimeError(f"session/load failed: {resp['error']}")
        load_result: dict[str, Any] = resp.get("result", {})
        return load_result

    async def list_sessions(self) -> dict[str, Any]:
        """List available sessions.

        Returns:
            Dict with "sessions" list and optional "nextCursor".

        Raises:
            asyncio.TimeoutError: If no response within 30 seconds.
            ConnectionError: If not connected.
            RuntimeError: If the server returns an error.
        """
        resp = await self._send_rpc_request("session/list")
        if "error" in resp:
            raise RuntimeError(f"session/list failed: {resp['error']}")
        list_result: dict[str, Any] = resp.get("result", {})
        return list_result

    async def send_prompt(
        self,
        session_id: str,
        text: str,
        images: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
        timeout: float = DEFAULT_PROMPT_TIMEOUT,
    ) -> PromptResponse:
        """Send a prompt to K2 and collect all streaming updates until the final result.

        This is a blocking call that waits for the complete response. For
        streaming iteration, use send_prompt_stream() instead.

        Args:
            session_id: The session to send the prompt in.
            text: The text content of the prompt.
            images: Optional list of image content blocks.
            files: Optional list of file content blocks.
            timeout: Maximum seconds to wait for the complete response.

        Returns:
            PromptResponse containing all streaming updates and the final result.

        Raises:
            asyncio.TimeoutError: If no complete response within timeout.
            ConnectionError: If not connected.
        """
        content_blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if images:
            content_blocks.extend(images)
        if files:
            content_blocks.extend(files)

        req_id = self._next_request_id()
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": {"content": content_blocks},
            },
        }

        # Set up streaming collection
        self._streaming_updates[req_id] = []
        self._streaming_events[req_id] = asyncio.Event()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_requests[req_id] = future

        await self._send_raw(msg)

        response = PromptResponse()
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            response.updates = self._streaming_updates.get(req_id, [])
            if "error" in result:
                response.error = result["error"]
            elif "result" in result:
                response.result = PromptResult.from_result(result["result"])
        except TimeoutError:
            self._pending_requests.pop(req_id, None)
            response.updates = self._streaming_updates.get(req_id, [])
            response.error = {
                "code": AcpErrorCode.PROMPT_TIMEOUT,
                "message": "Prompt timed out",
            }
        finally:
            self._streaming_updates.pop(req_id, None)
            self._streaming_events.pop(req_id, None)

        return response

    async def send_prompt_stream(
        self,
        session_id: str,
        text: str,
        images: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
        timeout: float = DEFAULT_PROMPT_TIMEOUT,
    ) -> AsyncIterator[SessionUpdate | PromptResult]:
        """Send a prompt to K2 and yield streaming updates as they arrive.

        Yields SessionUpdate objects for each chunk, then a final PromptResult.

        Args:
            session_id: The session to send the prompt in.
            text: The text content of the prompt.
            images: Optional list of image content blocks.
            files: Optional list of file content blocks.
            timeout: Maximum seconds to wait for the complete response.

        Yields:
            SessionUpdate for each streaming update, then PromptResult for the final result.

        Raises:
            asyncio.TimeoutError: If no complete response within timeout.
            ConnectionError: If not connected.
        """
        content_blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if images:
            content_blocks.extend(images)
        if files:
            content_blocks.extend(files)

        req_id = self._next_request_id()
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": {"content": content_blocks},
            },
        }

        # Set up streaming collection with a queue for async iteration
        update_queue: asyncio.Queue[SessionUpdate | PromptResult | None] = asyncio.Queue()
        self._streaming_updates[req_id] = []
        self._streaming_queues[req_id] = update_queue

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_requests[req_id] = future

        await self._send_raw(msg)

        deadline = asyncio.get_event_loop().time() + timeout
        try:
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError("Prompt stream timed out")
                item = await asyncio.wait_for(update_queue.get(), timeout=remaining)
                if item is None:
                    # Stream complete
                    break
                yield item
        finally:
            self._streaming_updates.pop(req_id, None)
            self._streaming_queues.pop(req_id, None)
            self._pending_requests.pop(req_id, None)

    async def cancel_prompt(self, session_id: str, request_id: str) -> dict[str, Any]:
        """Cancel an in-progress prompt.

        Args:
            session_id: The session containing the prompt.
            request_id: The request ID of the prompt to cancel.

        Returns:
            The result dict from the server.

        Raises:
            asyncio.TimeoutError: If no response within 30 seconds.
            ConnectionError: If not connected.
        """
        resp = await self._send_rpc_request(
            "session/cancel",
            {"sessionId": session_id, "requestId": request_id},
        )
        cancel_result: dict[str, Any] = resp.get("result", {})
        return cancel_result

    # --- Server-Side Response Helpers ---

    async def send_session_update(
        self,
        session_id: str,
        update_type: str,
        content: dict[str, Any] | list[dict[str, Any]],
        request_id: str,
        tool_call_id: str | None = None,
        title: str | None = None,
        status: str | None = None,
    ) -> None:
        """Send a session/update notification (server mode: we respond to Kimi users).

        Args:
            session_id: The session ID.
            update_type: The update type (e.g. "agent_message_chunk").
            content: The content dict or list of content blocks (for tool calls).
            request_id: The request ID this responds to.
            tool_call_id: Tool call ID (for tool_call/tool_call_update types).
            title: Tool title (for tool_call/tool_call_update types).
            status: Tool status e.g. "in_progress" or "completed".
        """
        msg = build_session_update(
            session_id=session_id,
            update_type=update_type,
            content=content,
            request_id=request_id,
            meta_index=self._next_meta_index(),
            tool_call_id=tool_call_id,
            title=title,
            status=status,
        )
        await self._send_raw(msg)

    async def send_agent_message(
        self,
        session_id: str,
        text: str,
        request_id: str,
    ) -> None:
        """Convenience: send an agent_message_chunk with text content.

        Args:
            session_id: The session ID.
            text: The text to send.
            request_id: The request ID this responds to.
        """
        await self.send_session_update(
            session_id=session_id,
            update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK,
            content={"type": "text", "text": text},
            request_id=request_id,
        )

    async def send_agent_thought(
        self,
        session_id: str,
        text: str,
        request_id: str,
    ) -> None:
        """Convenience: send an agent_thought_chunk with text content.

        Args:
            session_id: The session ID.
            text: The thought text to send.
            request_id: The request ID this responds to.
        """
        await self.send_session_update(
            session_id=session_id,
            update_type=SessionUpdateType.AGENT_THOUGHT_CHUNK,
            content={"type": "text", "text": text},
            request_id=request_id,
        )

    async def send_tool_call(
        self,
        session_id: str,
        tool_call_id: str,
        title: str,
        content: list[dict[str, Any]],
        request_id: str,
    ) -> None:
        """Convenience: send a tool_call notification (tool invocation started).

        Per the protocol, sends a newline spacer agent_message_chunk before the
        tool_call for formatting.

        Args:
            session_id: The session ID.
            tool_call_id: Unique ID for this tool call.
            title: Tool display name (e.g. "Bash").
            content: List of content blocks describing the call.
            request_id: The request ID this responds to.
        """
        # Newline spacer per protocol spec
        await self.send_agent_message(session_id=session_id, text="\n", request_id=request_id)
        await self.send_session_update(
            session_id=session_id,
            update_type=SessionUpdateType.TOOL_CALL,
            content=content,
            request_id=request_id,
            tool_call_id=tool_call_id,
            title=title,
            status="in_progress",
        )

    async def send_tool_result(
        self,
        session_id: str,
        tool_call_id: str,
        title: str,
        content: list[dict[str, Any]],
        request_id: str,
    ) -> None:
        """Convenience: send a tool_call_update notification (tool result).

        Per the protocol, sends a newline spacer agent_message_chunk before the
        tool_call_update for formatting.

        Args:
            session_id: The session ID.
            tool_call_id: The tool call ID from the original tool_call.
            title: Tool display name.
            content: List of content blocks with the result.
            request_id: The request ID this responds to.
        """
        # Newline spacer per protocol spec
        await self.send_agent_message(session_id=session_id, text="\n", request_id=request_id)
        await self.send_session_update(
            session_id=session_id,
            update_type=SessionUpdateType.TOOL_CALL_UPDATE,
            content=content,
            request_id=request_id,
            tool_call_id=tool_call_id,
            title=title,
            status="completed",
        )

    async def send_result(
        self,
        request_id: str,
        result: dict[str, Any] | None,
        session_id: str | None = None,
    ) -> None:
        """Send a JSON-RPC result response (server mode: completing a request from Kimi).

        Args:
            request_id: The request ID being responded to.
            result: The result payload (can be None for empty results like session/load).
            session_id: Optional session ID for _meta.
        """
        msg = build_result(
            request_id=request_id,
            result=result,
            session_id=session_id,
            meta_index=self._next_meta_index(),
        )
        await self._send_raw(msg)

    async def send_error(
        self,
        request_id: str | None,
        code: int,
        message: str,
    ) -> None:
        """Send a JSON-RPC error response.

        Args:
            request_id: The request ID (None for notification errors).
            code: ACP error code.
            message: Error description.
        """
        msg = build_error(
            request_id=request_id,
            code=code,
            message=message,
            meta_index=self._next_meta_index(),
        )
        await self._send_raw(msg)

    # --- Message Listener ---

    async def _listener_loop(self) -> None:
        """Main message listener loop.

        Receives messages from the WebSocket and routes them:
        - Text "ping" / "pong": handle heartbeats
        - JSON {"type": "ping"}: respond with {"type": "pong"}
        - JSON-RPC response (has id + result/error): resolve pending future
        - JSON-RPC request (has id + method, no result/error): server-side handler
        - JSON-RPC notification (has method, no id): handle session/update, reconnect, etc.
        """
        try:
            while self._connected and self._ws:
                try:
                    raw_msg = await self._ws.recv()
                except websockets.exceptions.ConnectionClosed as e:
                    close_code = getattr(e, "code", 0)
                    logger.info("Kimi bridge connection closed (code=%s)", close_code)

                    if close_code == 4001:
                        self._auth_failed = True
                        logger.error("Auth failed (WS close 4001) -- will not retry")
                        self._connected = False
                        return

                    self._connected = False
                    if self.auto_reconnect and not self._closing:
                        await self._schedule_reconnect()
                    return

                # Update liveness timestamp on any received data
                self._last_data_received = time.monotonic()

                # Handle text heartbeats
                if isinstance(raw_msg, str):
                    stripped = raw_msg.strip().lower()
                    if stripped == "ping":
                        try:
                            await self._ws.send("pong")
                        except Exception:
                            pass
                        continue
                    if stripped == "pong":
                        continue

                # Parse JSON
                try:
                    if isinstance(raw_msg, bytes):
                        data = json.loads(raw_msg.decode("utf-8"))
                    else:
                        data = json.loads(raw_msg)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.warning("Received non-JSON message: %s", str(raw_msg)[:200])
                    continue

                # JSON ping/pong
                if data.get("type") == "ping":
                    try:
                        await self._ws.send(json.dumps({"type": "pong"}))
                    except Exception:
                        pass
                    continue
                if data.get("type") == "pong":
                    continue

                # Reset reconnect timer on any real message
                if self._reconnect_timer_task and not self._reconnect_timer_task.done():
                    self._reconnect_timer_task.cancel()
                    self._reconnect_timer_task = None

                # Route the message
                await self._route_message(data)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Kimi bridge listener error")
            self._connected = False
            if self.auto_reconnect and not self._closing:
                await self._schedule_reconnect()

    async def _route_message(self, data: dict[str, Any]) -> None:
        """Route a parsed JSON-RPC message to the appropriate handler."""

        has_id = "id" in data
        has_result = "result" in data
        has_error = "error" in data
        has_method = "method" in data

        # JSON-RPC response: has id and (result or error)
        if has_id and (has_result or has_error):
            await self._handle_response(data)
            return

        # JSON-RPC request from Kimi: has id and method (but no result/error)
        if has_id and has_method and not has_result and not has_error:
            await self._handle_incoming_request(data)
            return

        # JSON-RPC notification: has method but no id
        if has_method and not has_id:
            await self._handle_notification(data)
            return

        logger.debug("Unroutable message: %s", json.dumps(data, ensure_ascii=False)[:200])

    async def _handle_response(self, data: dict[str, Any]) -> None:
        """Handle a JSON-RPC response (resolve a pending request future).

        If the response corresponds to a streaming prompt, also pushes the
        final PromptResult to the streaming queue followed by a None sentinel
        to signal completion.
        """
        req_id = data.get("id")
        if not req_id:
            return

        # Push to streaming queue if present (for send_prompt_stream)
        if req_id in self._streaming_queues:
            queue = self._streaming_queues[req_id]
            if "result" in data:
                await queue.put(PromptResult.from_result(data["result"]))
            await queue.put(None)  # Sentinel: stream complete

        if req_id in self._pending_requests:
            future = self._pending_requests.pop(req_id)
            if not future.done():
                future.set_result(data)
        else:
            logger.debug("Response for unknown request: %s", req_id)

    async def _handle_notification(self, data: dict[str, Any]) -> None:
        """Handle a JSON-RPC notification (no id)."""
        method = data.get("method", "")

        if method == "session/update":
            params = data.get("params", {})
            update = SessionUpdate.from_params(params)
            meta = params.get("_meta", {})
            request_id = meta.get("requestId", "")

            # Push to streaming collection for the relevant request
            if request_id and request_id in self._streaming_updates:
                self._streaming_updates[request_id].append(update)

            # Push to streaming queue if one exists (for send_prompt_stream)
            if request_id and request_id in self._streaming_queues:
                await self._streaming_queues[request_id].put(update)

            # Log for observability
            if update.update_type == SessionUpdateType.AGENT_MESSAGE_CHUNK:
                logger.debug("K2 chunk: %s", update.text[:100] if update.text else "")
            elif update.update_type == SessionUpdateType.TOOL_CALL:
                logger.debug("K2 tool call: %s", update.title)
            elif update.update_type == SessionUpdateType.TOOL_CALL_UPDATE:
                logger.debug("K2 tool result: %s", update.title)

        elif method == "_kimi.com/reconnect":
            await self._handle_reconnect_notification()

        else:
            logger.debug("Unhandled notification: %s", method)

    async def _handle_incoming_request(self, data: dict[str, Any]) -> None:
        """Handle an incoming JSON-RPC request from Kimi (server mode).

        Kimi is asking US to do something (initialize, create session, handle prompt, etc).
        """
        method = data.get("method", "")
        raw_id = data.get("id")
        req_id: str | None = str(raw_id) if raw_id is not None else None
        params = data.get("params", {})

        logger.info("Incoming ACP request: method=%s id=%s", method, req_id)

        if method == "initialize":
            if self._on_initialize and req_id is not None:
                await self._on_initialize(req_id, params, self)
            elif req_id is not None:
                await self._default_on_initialize(req_id, params)

        elif method == "session/new":
            if self._on_session_new and req_id is not None:
                await self._on_session_new(req_id, params, self)
            elif req_id is not None:
                await self._default_on_session_new(req_id, params)

        elif method == "session/load":
            # Default: acknowledge load with empty result
            if req_id is not None:
                await self.send_result(req_id, None)

        elif method == "session/list":
            # Default: empty session list
            if req_id is not None:
                await self.send_result(req_id, {"sessions": [], "nextCursor": None})

        elif method == "session/prompt":
            if self._on_session_prompt and req_id is not None:
                try:
                    await self._on_session_prompt(req_id, params, self)
                except Exception:
                    logger.exception("session/prompt handler error for id=%s", req_id)
                    await self.send_error(
                        req_id,
                        AcpErrorCode.GATEWAY_ERROR,
                        "Internal handler error",
                    )
            elif req_id is not None:
                # Default: echo the message back
                await self._default_on_session_prompt(req_id, params)

        elif method == "session/cancel":
            if self._on_session_cancel and req_id is not None:
                await self._on_session_cancel(req_id, params, self)
            elif req_id is not None:
                await self.send_result(req_id, {})

        elif method == "session/set_model":
            if req_id is not None:
                await self.send_result(req_id, {})

        else:
            logger.warning("Unknown incoming method: %s", method)
            if req_id is not None:
                await self.send_error(
                    req_id,
                    AcpErrorCode.METHOD_NOT_FOUND,
                    f"Method not found: {method}",
                )

    # --- Default Server-Side Handlers ---

    async def _default_on_initialize(self, req_id: str, params: dict[str, Any]) -> None:
        """Default handler for incoming initialize requests."""
        await self.send_result(
            req_id,
            {
                "protocolVersion": 1,
                "agentCapabilities": self.capabilities.to_dict(),
                "agentInfo": self.agent_info.to_dict(),
            },
        )

    async def _default_on_session_new(self, req_id: str, params: dict[str, Any]) -> None:
        """Default handler for incoming session/new requests."""
        session_info = SessionInfo(
            session_id="agent:main:main",
            available_modes=[
                SessionMode(id="default", name="Default", description="Default agent mode"),
            ],
            current_mode_id="default",
        )
        await self.send_result(req_id, session_info.to_dict())

    async def _default_on_session_prompt(self, req_id: str, params: dict[str, Any]) -> None:
        """Default handler for incoming session/prompt: echoes the user message."""
        prompt = params.get("prompt", {}) if isinstance(params, dict) else {}
        user_text = extract_prompt_text(prompt)
        session_id = params.get("sessionId", "agent:main:main") if isinstance(params, dict) else "agent:main:main"

        logger.info("Incoming user message (default echo handler): %s", user_text[:200])

        # Echo user message
        await self.send_session_update(
            session_id=session_id,
            update_type=SessionUpdateType.USER_MESSAGE_CHUNK,
            content={"type": "text", "text": user_text},
            request_id=req_id,
        )

        # Send echo response
        response_text = f'Hello from {self.agent_info.name}! You said: "{user_text[:200]}"'
        await self.send_agent_message(
            session_id=session_id,
            text=response_text,
            request_id=req_id,
        )

        # Complete
        await self.send_result(
            req_id,
            {"stopReason": StopReason.END_TURN},
            session_id=session_id,
        )

    # --- Context Manager ---

    async def __aenter__(self) -> KimiBridgeClient:
        """Connect when entering async context."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Disconnect when exiting async context."""
        await self.disconnect()

    # --- Run loop (blocking) ---

    async def run_forever(self) -> None:
        """Run the bridge client indefinitely, reconnecting as needed.

        This is a convenience method for server mode: connects and then blocks
        forever, handling incoming requests via callbacks. Reconnects automatically
        on disconnect.

        Raises:
            ConnectionError: If auth fails permanently.
        """
        if not self._connected:
            await self.connect()

        if self._auth_failed:
            raise ConnectionError("Authentication failed -- cannot run")

        # Wait for the listener to finish (which only happens on permanent failure)
        while not self._closing and not self._auth_failed:
            if self._listener_task:
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    break
            # If listener finished but we should reconnect, wait a bit
            if self.auto_reconnect and not self._closing and not self._auth_failed:
                await asyncio.sleep(1.0)
            else:
                break
