"""In-process gateway protocol adapter for the Corvus TUI.

Runs the full Corvus gateway in the same process as the TUI, bypassing
WebSocket transport entirely.  Events are intercepted from the
SessionEmitter and forwarded to the TUI via the registered callback.
"""

import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from corvus.gateway.chat_session import ChatSession
from corvus.gateway.runtime import GatewayRuntime, build_runtime
from corvus.gateway.workspace_runtime import cleanup_session_workspaces
from corvus.memory.record import MemoryRecord
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
        """Build the gateway runtime in-process and start all services.

        Mirrors the server lifespan: LiteLLM proxy, supervisor heartbeat,
        scheduler, model discovery.
        """
        if self._connected:
            return
        self._runtime = build_runtime()

        # Start LiteLLM proxy (sets ANTHROPIC_BASE_URL for router)
        try:
            await self._runtime.litellm_manager.start(Path("config/models.yaml"))
            logger.info("LiteLLM proxy started")
        except Exception as exc:
            logger.warning("LiteLLM proxy failed to start: %s", exc)

        self._runtime.model_router.discover_models()

        # Start supervisor heartbeat
        await self._runtime.supervisor.start()
        logger.info("AgentSupervisor heartbeat started")

        # Start scheduler
        self._runtime.scheduler.load()
        await self._runtime.scheduler.start()
        logger.info("CronScheduler started")

        self._connected = True
        logger.info("In-process gateway connected (full stack)")

    async def disconnect(self) -> None:
        """Tear down the runtime — stop LiteLLM, supervisor, scheduler, cleanup workspaces."""
        # Clean up session workspaces before tearing down runtime
        if self._session is not None:
            try:
                cleanup_session_workspaces(session_id=self._session.session_id)
            except Exception:
                logger.warning("Failed to cleanup workspaces for session %s", self._session.session_id)

        if self._runtime is not None:
            try:
                await self._runtime.litellm_manager.stop()
            except Exception:
                pass
            try:
                await self._runtime.supervisor.graceful_shutdown()
            except Exception:
                pass
            try:
                await self._runtime.scheduler.stop()
            except Exception:
                pass
        self._session = None
        self._runtime = None
        self._connected = False
        logger.info("In-process gateway disconnected")

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(self, text: str, *, session_id: str | None = None, requested_agent: str | None = None) -> None:
        """Send a user message through the in-process gateway.

        Creates or reuses a ChatSession with websocket=None.  The emitter's
        ws_send is replaced with a closure that intercepts outbound payloads,
        parses them into ProtocolEvent objects, and forwards them to the
        registered callback.
        """
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before send_message()")

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
        from corvus.gateway.chat_engine import resolve_chat_dispatch

        turn_id = str(uuid.uuid4())
        dispatch_id = str(uuid.uuid4())
        session.current_turn_id = turn_id

        try:
            dispatch_resolution, dispatch_error = await resolve_chat_dispatch(
                runtime=self._runtime,
                user_message=text,
                requested_agent=requested_agent,
                requested_agents=None,
                requested_model=None,
                dispatch_mode_raw=None,
            )
        except Exception as exc:
            logger.exception("Dispatch resolution failed")
            if callback is not None:
                error_event = parse_event({
                    "type": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                })
                await callback(error_event)
            session.current_turn_id = None
            return

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

        if dispatch_resolution is None:
            raise RuntimeError("Dispatch resolution returned None without an error — this should not happen")
        try:
            await session._execute_dispatch_lifecycle(
                dispatch_id=dispatch_id,
                turn_id=turn_id,
                resolution=dispatch_resolution,
                user_message=text,
                user_model=None,
                requires_tools=False,
            )
        except Exception as exc:
            logger.exception("Dispatch execution failed")
            if callback is not None:
                error_event = parse_event({
                    "type": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                })
                await callback(error_event)

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
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before list_sessions()")

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
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before resume_session()")

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
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before list_agents()")

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
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before list_models()")

        models = self._runtime.model_router.list_available_models()
        return [m.to_dict() for m in models]

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories via the runtime's MemoryHub."""
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before memory_search()")

        results = await self._runtime.memory_hub.search(
            query, agent_name=agent_name, limit=limit,
        )
        return [r.to_dict() for r in results]

    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """List recent memories via the runtime's MemoryHub."""
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before memory_list()")

        results = await self._runtime.memory_hub.list_memories(
            agent_name=agent_name, limit=limit,
        )
        return [r.to_dict() for r in results]

    async def memory_save(self, content: str, agent_name: str) -> str:
        """Save a new memory via the runtime's MemoryHub."""
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before memory_save()")

        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=content,
            domain="shared",
            source="tui",
            created_at=datetime.now(UTC).isoformat(),
        )
        return await self._runtime.memory_hub.save(record, agent_name=agent_name)

    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        """Soft-delete a memory via the runtime's MemoryHub."""
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before memory_forget()")

        return await self._runtime.memory_hub.forget(record_id, agent_name=agent_name)

    # ------------------------------------------------------------------
    # Tool queries
    # ------------------------------------------------------------------

    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        """Return tool definitions from the agent's spec."""
        if self._runtime is None:
            raise RuntimeError("Gateway not connected — call connect() before list_agent_tools()")

        spec = self._runtime.agent_registry.get(agent_name)
        if spec is None:
            return []

        tools: list[dict[str, Any]] = []
        for tool_name in spec.tools.builtin:
            tools.append({
                "name": tool_name,
                "type": "builtin",
                "description": "",
            })

        for module_name, module_config in spec.tools.modules.items():
            tools.append({
                "name": module_name,
                "type": "module",
                "description": str(module_config) if module_config else "",
            })

        for mcp_server in spec.tools.mcp_servers:
            server_name = mcp_server.get("name", "unknown")
            tools.append({
                "name": server_name,
                "type": "mcp",
                "description": mcp_server.get("description", ""),
            })

        return tools

    # ------------------------------------------------------------------
    # Event callback
    # ------------------------------------------------------------------

    def on_event(
        self,
        callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an async callback to receive protocol events."""
        self._event_callback = callback
