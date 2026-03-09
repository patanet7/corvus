"""In-process gateway protocol adapter for the Corvus TUI.

Runs the full Corvus gateway in the same process as the TUI, bypassing
WebSocket transport entirely.  Events are intercepted from the
SessionEmitter and forwarded to the TUI via the registered callback.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from corvus.gateway.chat_session import ChatSession
from corvus.gateway.runtime import GatewayRuntime, build_runtime
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event

logger = logging.getLogger("corvus-tui.in-process")


class InProcessGateway(GatewayProtocol):
    """In-process gateway that runs the Corvus runtime directly.

    No WebSocket, no HTTP -- the TUI drives ChatSession objects in-process
    and receives events via an intercepted emitter callback.
    """

    def __init__(self) -> None:
        self._runtime: GatewayRuntime | None = None
        self._session: ChatSession | None = None
        self._event_callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]] | None = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Build the gateway runtime in-process."""
        if self._connected:
            return
        self._runtime = build_runtime()
        self._connected = True
        logger.info("In-process gateway connected")

    async def disconnect(self) -> None:
        """Tear down the runtime and clear session state."""
        self._session = None
        self._runtime = None
        self._connected = False
        logger.info("In-process gateway disconnected")

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(self, text: str, *, session_id: str | None = None) -> None:
        """Send a user message through the in-process gateway.

        Creates or reuses a ChatSession with websocket=None.  The emitter's
        ws_send is replaced with a closure that intercepts outbound payloads,
        parses them into ProtocolEvent objects, and forwards them to the
        registered callback.
        """
        assert self._runtime is not None, "connect() must be called before send_message()"

        sid = session_id or (self._session.session_id if self._session else str(uuid.uuid4()))

        # Create or reuse session
        if self._session is None or self._session.session_id != sid:
            self._session = ChatSession(
                runtime=self._runtime,
                websocket=None,
                user="tui",
                session_id=sid,
            )
            # Register session in session manager
            self._runtime.session_mgr.start(sid, user="tui", started_at=datetime.now())

        session = self._session

        # Intercept emitter ws_send to capture events
        callback = self._event_callback

        async def _intercept_ws_send(payload: dict) -> None:
            if callback is not None:
                event = parse_event(payload)
                await callback(event)

        session.emitter._ws_send_fn = _intercept_ws_send

        # Build a dispatch through the session's normal pipeline
        from corvus.gateway.chat_engine import resolve_chat_dispatch, resolve_default_agent

        turn_id = str(uuid.uuid4())
        dispatch_id = str(uuid.uuid4())
        session.current_turn_id = turn_id

        dispatch_resolution, dispatch_error = await resolve_chat_dispatch(
            runtime=self._runtime,
            user_message=text,
            requested_agent=None,
            requested_agents=None,
            requested_model=None,
            dispatch_mode_raw=None,
        )

        if dispatch_error:
            if callback is not None:
                error_event = parse_event({
                    "type": "error",
                    "error": dispatch_error.error,
                    "message": dispatch_error.message,
                })
                await callback(error_event)
            session.current_turn_id = None
            return

        assert dispatch_resolution is not None
        await session._execute_dispatch_lifecycle(
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            resolution=dispatch_resolution,
            user_message=text,
            user_model=None,
            requires_tools=False,
        )

    # ------------------------------------------------------------------
    # Confirmation / cancellation
    # ------------------------------------------------------------------

    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        """Forward a confirmation response to the active session's confirm queue."""
        if self._session is not None:
            self._session.confirm_queue.respond(tool_id, approved=approved)

    async def cancel_run(self, run_id: str) -> None:
        """Set the dispatch_interrupted flag on the current turn."""
        if self._session is not None and self._session._current_turn is not None:
            self._session._current_turn.dispatch_interrupted.set()

    # ------------------------------------------------------------------
    # Session queries
    # ------------------------------------------------------------------

    async def list_sessions(self) -> list[SessionSummary]:
        """Return summaries of all sessions from the session manager."""
        assert self._runtime is not None, "connect() must be called before list_sessions()"

        rows = self._runtime.session_mgr.list()
        summaries: list[SessionSummary] = []
        for row in rows:
            agents_used_raw = row.get("agents_used", [])
            if isinstance(agents_used_raw, str):
                try:
                    agents_used_raw = json.loads(agents_used_raw)
                except (json.JSONDecodeError, TypeError):
                    agents_used_raw = []
            if not isinstance(agents_used_raw, list):
                agents_used_raw = []

            started_at = row.get("started_at")
            if isinstance(started_at, str):
                try:
                    started_at = datetime.fromisoformat(started_at)
                except ValueError:
                    started_at = None

            summaries.append(SessionSummary(
                session_id=row.get("id", ""),
                agent_name=row.get("agent_name", ""),
                summary=row.get("summary", ""),
                started_at=started_at,
                message_count=row.get("message_count", 0),
                agents_used=agents_used_raw,
            ))
        return summaries

    async def resume_session(self, session_id: str) -> SessionDetail:
        """Load full session detail including message history."""
        assert self._runtime is not None, "connect() must be called before resume_session()"

        session_row = self._runtime.session_mgr.get(session_id)
        if session_row is None:
            return SessionDetail(session_id=session_id)

        messages = self._runtime.session_mgr.list_messages(session_id)

        agents_used_raw = session_row.get("agents_used", [])
        if isinstance(agents_used_raw, str):
            try:
                agents_used_raw = json.loads(agents_used_raw)
            except (json.JSONDecodeError, TypeError):
                agents_used_raw = []
        if not isinstance(agents_used_raw, list):
            agents_used_raw = []

        started_at = session_row.get("started_at")
        if isinstance(started_at, str):
            try:
                started_at = datetime.fromisoformat(started_at)
            except ValueError:
                started_at = None

        return SessionDetail(
            session_id=session_id,
            agent_name=session_row.get("agent_name", ""),
            summary=session_row.get("summary", ""),
            started_at=started_at,
            message_count=session_row.get("message_count", 0),
            agents_used=agents_used_raw,
            messages=[dict(m) for m in messages],
        )

    # ------------------------------------------------------------------
    # Agent / model queries
    # ------------------------------------------------------------------

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return metadata for all enabled agents."""
        assert self._runtime is not None, "connect() must be called before list_agents()"

        specs = self._runtime.agent_registry.list_enabled()
        return [
            {
                "id": spec.name,
                "label": spec.name.title(),
                "description": spec.description,
                "enabled": spec.enabled,
            }
            for spec in specs
        ]

    async def list_models(self) -> list[dict[str, Any]]:
        """Return metadata for all available models."""
        assert self._runtime is not None, "connect() must be called before list_models()"

        models = self._runtime.model_router.list_available_models()
        return [m.to_dict() for m in models]

    # ------------------------------------------------------------------
    # Event callback
    # ------------------------------------------------------------------

    def on_event(
        self,
        callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an async callback to receive protocol events."""
        self._event_callback = callback
