"""ChatSession class — WebSocket chat lifecycle extracted from closure soup.

Converts the deeply nested closures in corvus/api/chat.py into a class with
explicit instance state. Session-lifetime state lives on the instance;
per-turn state is scoped via TurnContext.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from corvus.gateway.confirm_queue import ConfirmQueue
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import WebSocket

from corvus.gateway.chat_engine import ChatDispatchResolution, resolve_chat_dispatch, resolve_default_agent
from corvus.gateway.dispatch_orchestrator import (
    dispatch_control_listener as _dispatch_control,
    execute_dispatch_lifecycle as _execute_dispatch,
)
from corvus.gateway.options import (
    any_llm_configured,
    ui_default_model,
)
from corvus.gateway.run_executor import execute_agent_run as _execute_run
from corvus.gateway.runtime import GatewayRuntime
from corvus.gateway.session_emitter import (
    SessionEmitter,
    _PERSISTED_RUN_EVENT_TYPES,
    _PERSISTED_SESSION_EVENT_TYPES,
    _TRACE_EVENT_TYPES,
    _optional_str,
    _preview_summary,
    _trace_source_app,
    _trace_summary,
)
from corvus.gateway.task_planner import TaskRoute
from corvus.session import SessionTranscript

logger = logging.getLogger("corvus-gateway")


# ---------------------------------------------------------------------------
# Per-turn state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TurnContext:
    """Per-turn dispatch state — created fresh each turn, passed to methods."""

    dispatch_id: str
    turn_id: str
    dispatch_interrupted: asyncio.Event
    user_model: str | None
    requires_tools: bool


# Re-export event type sets and helpers from session_emitter for backward compat.
# These names are imported above; this comment documents why they're in this
# module's namespace: existing tests and callers import them from chat_session.
__all_reexports__ = [
    "_PERSISTED_SESSION_EVENT_TYPES",
    "_PERSISTED_RUN_EVENT_TYPES",
    "_TRACE_EVENT_TYPES",
    "_preview_summary",
    "_optional_str",
    "_trace_source_app",
    "_trace_summary",
]


# ---------------------------------------------------------------------------
# ChatSession class
# ---------------------------------------------------------------------------


class ChatSession:
    """WebSocket chat session lifecycle.

    Replaces the closure soup in websocket_chat() with explicit instance state.
    Session-lifetime state lives on the instance; per-turn state is scoped via
    TurnContext passed to methods.
    """

    def __init__(
        self,
        *,
        runtime: GatewayRuntime,
        websocket: WebSocket | None,
        user: str,
        session_id: str,
    ) -> None:
        self.runtime = runtime
        self.websocket = websocket
        self.user = user
        self.session_id = session_id
        self._current_turn: TurnContext | None = None
        self.transcript = SessionTranscript(
            user=user,
            session_id=session_id,
            messages=[],
        )
        self.confirm_queue = ConfirmQueue()

        # Create ws_send callable wrapping self.websocket.
        # NOTE: The emitter's _ws_send already acquires send_lock before
        # calling this, so no lock here to avoid deadlock.
        async def _ws_send(payload: dict) -> None:
            if self.websocket is not None:
                await self.websocket.send_json(payload)

        self.emitter = SessionEmitter(
            runtime=runtime,
            ws_send=_ws_send if websocket is not None else None,
            session_id=session_id,
            user=user,
        )

        # Shared lock — use the emitter's lock as the canonical one
        self.send_lock = self.emitter.send_lock

        # Delegate send/persist/trace/emit methods to the emitter
        self.send = self.emitter.send  # type: ignore[assignment]
        self._ws_send = self.emitter._ws_send  # type: ignore[assignment]
        self._persist_session_event = self.emitter._persist_session_event  # type: ignore[assignment]
        self._persist_run_event = self.emitter._persist_run_event  # type: ignore[assignment]
        self._publish_trace = self.emitter._publish_trace  # type: ignore[assignment]
        self._emit_phase = self.emitter.emit_phase  # type: ignore[assignment]
        self._emit_run_failure = self.emitter.emit_run_failure  # type: ignore[assignment]
        self._emit_run_interrupted = self.emitter.emit_run_interrupted  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Public API for in-process / non-WebSocket callers
    # ------------------------------------------------------------------

    def set_ws_interceptor(
        self,
        interceptor: Callable[[dict], Coroutine[Any, Any, None]] | None,
    ) -> None:
        """Replace the emitter's WebSocket send function.

        Used by in-process gateways (e.g. the TUI) to intercept outbound
        payloads without a real WebSocket connection.
        """
        self.emitter._ws_send_fn = interceptor

    async def execute_dispatch(
        self,
        *,
        dispatch_id: str,
        turn_id: str,
        resolution: ChatDispatchResolution,
        user_message: str,
        user_model: str | None,
        requires_tools: bool,
    ) -> None:
        """Public wrapper around the dispatch lifecycle.

        Delegates to the same internal pipeline used by the WebSocket
        message loop, but callable from non-WebSocket callers.
        """
        await self._execute_dispatch_lifecycle(
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            resolution=resolution,
            user_message=user_message,
            user_model=user_model,
            requires_tools=requires_tools,
        )

    def interrupt_current_turn(self) -> None:
        """Signal the current dispatch turn to stop.

        No-op if there is no active turn.
        """
        if self._current_turn is not None:
            self._current_turn.dispatch_interrupted.set()

    # ------------------------------------------------------------------
    # current_turn_id — proxied to emitter for consistency
    # ------------------------------------------------------------------

    @property
    def current_turn_id(self) -> str | None:
        return self.emitter.current_turn_id

    @current_turn_id.setter
    def current_turn_id(self, value: str | None) -> None:
        self.emitter.current_turn_id = value

    # ------------------------------------------------------------------
    # Payload builder (delegates to SessionEmitter.base_payload)
    # ------------------------------------------------------------------

    @staticmethod
    def _base_payload(
        *,
        turn: TurnContext,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        session_id: str,
    ) -> dict:
        """Build the common payload dict shared by all run events."""
        return SessionEmitter.base_payload(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Route payload helper
    # ------------------------------------------------------------------

    @staticmethod
    def _route_payload(route: TaskRoute, *, route_index: int) -> dict:
        """Build route-level payload fields for event enrichment."""
        return {
            "task_type": route.task_type,
            "subtask_id": route.subtask_id,
            "skill": route.skill,
            "instruction": route.instruction,
            "route_index": route_index,
        }

    # ------------------------------------------------------------------
    # execute_agent_run — delegates to corvus.gateway.run_executor
    # ------------------------------------------------------------------

    async def execute_agent_run(self, route: TaskRoute, *, route_index: int) -> dict:
        """Execute a single agent run for one route in a dispatch plan.

        Delegates to the extracted ``run_executor.execute_agent_run`` function,
        passing all dependencies explicitly.
        """
        turn = self._current_turn
        if turn is None:
            raise RuntimeError("execute_agent_run requires an active TurnContext")
        return await _execute_run(
            emitter=self.emitter,
            runtime=self.runtime,
            turn=turn,
            route=route,
            route_index=route_index,
            transcript=self.transcript,
            websocket=self.websocket,
            user=self.user,
            confirm_queue=self.confirm_queue,
            sdk_manager=self.runtime.sdk_client_manager,
        )

    # ------------------------------------------------------------------
    # dispatch_control_listener — ported from corvus/api/chat.py lines 1059-1112
    # ------------------------------------------------------------------

    async def dispatch_control_listener(self) -> None:
        """Listen for interrupt/ping/confirm messages during active dispatch."""
        await _dispatch_control(self)

    # ------------------------------------------------------------------
    # _degraded_message_loop — ported from corvus/api/chat.py lines 133-155
    # ------------------------------------------------------------------

    async def _degraded_message_loop(self) -> None:
        """Run heartbeat/error loop when no LLM backend is configured."""
        if self.websocket is None:
            raise RuntimeError("_degraded_message_loop requires an active WebSocket")

        while True:
            data = await self.websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await self.websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            if msg.get("type") == "ping":
                await self.websocket.send_json({"type": "pong"})
                continue

            if msg.get("message"):
                await self.websocket.send_json(
                    {
                        "type": "error",
                        "error": "no_llm_configured",
                        "message": "No LLM backend configured. Run 'mise run setup' to add one.",
                    }
                )
                continue

    # ------------------------------------------------------------------
    # _execute_dispatch_lifecycle — dispatch setup, execution, summary, cleanup
    # ------------------------------------------------------------------

    async def _execute_dispatch_lifecycle(
        self,
        *,
        dispatch_id: str,
        turn_id: str,
        resolution: ChatDispatchResolution,
        user_message: str,
        user_model: str | None,
        requires_tools: bool,
    ) -> None:
        """Execute the full dispatch lifecycle for a single user turn."""
        await _execute_dispatch(
            self,
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            resolution=resolution,
            user_message=user_message,
            user_model=user_model,
            requires_tools=requires_tools,
        )

    # ------------------------------------------------------------------
    # run — main message loop
    # ------------------------------------------------------------------

    async def run(self, *, started_at: datetime, resumed_session: dict | None = None) -> None:
        """Core message-loop orchestration method.

        Sends the init message, then enters the main while-True loop
        processing incoming WebSocket messages: ping/pong, interrupts,
        confirm_response, and user chat messages dispatched through the
        planner/router/executor pipeline.
        """
        if self.websocket is None:
            raise RuntimeError("run() requires an active WebSocket")

        # --- Send init message ---
        enabled_agents = [agent for agent in self.runtime.agents_hub.list_agents() if agent.enabled]
        await self.websocket.send_json(
            {
                "type": "init",
                "models": [m.to_dict() for m in self.runtime.model_router.list_available_models()],
                "default_model": ui_default_model(self.runtime),
                "agents": [
                    {
                        "id": agent.name,
                        "label": agent.name.title(),
                        "description": agent.description,
                        "isDefault": agent.name == "general",
                    }
                    for agent in enabled_agents
                ],
                "default_agent": resolve_default_agent(self.runtime),
                "session_id": self.session_id,
                "session_name": (resumed_session or {}).get("summary") or "Huginn",
            }
        )

        # --- Degraded mode check ---
        if not any_llm_configured():
            logger.warning("No LLM backend configured; running in degraded mode")
            await self._degraded_message_loop()
            return

        # --- Main message loop ---
        while True:
            data = await self.websocket.receive_text()

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await self.send({"type": "error", "message": "Invalid JSON"})
                continue

            if msg.get("type") == "interrupt":
                logger.info("User interrupted session %s", self.session_id)
                # Interrupt via SDK client manager
                if self._current_turn is not None:
                    self._current_turn.dispatch_interrupted.set()
                    # Try SDK-level interrupt for all active agents
                    for client_info in self.runtime.sdk_client_manager.list_active_clients():
                        if client_info.session_id == self.session_id and client_info.active_run:
                            try:
                                await self.runtime.sdk_client_manager.interrupt(
                                    self.session_id, client_info.agent_name,
                                )
                            except Exception:
                                logger.warning(
                                    "SDK interrupt failed for %s/%s",
                                    self.session_id, client_info.agent_name,
                                    exc_info=True,
                                )
                await self.runtime.emitter.emit("session_interrupt", user=self.user, session_id=self.session_id)
                continue

            if msg.get("type") == "ping":
                await self.send({"type": "pong"})
                continue

            if msg.get("type") == "confirm_response":
                call_id = msg.get("tool_call_id")
                approved = msg.get("approved", False)
                logger.info("Confirm response: call_id=%s approved=%s", call_id, approved)
                await self.send(
                    {
                        "type": "confirm_response",
                        "tool_call_id": call_id,
                        "approved": bool(approved),
                    },
                    persist=True,
                )
                self.confirm_queue.respond(call_id, approved=bool(approved))
                continue

            user_message = msg.get("message", "")
            user_model_raw = msg.get("model")
            user_model = (
                str(user_model_raw).strip() if isinstance(user_model_raw, str) and user_model_raw.strip() else None
            )
            requested_agent = msg.get("target_agent")
            requested_agents = msg.get("target_agents")
            dispatch_mode_raw = msg.get("dispatch_mode")
            requires_tools = bool(msg.get("requires_tools", False))

            if not user_message:
                continue

            turn_id = str(uuid.uuid4())
            dispatch_id = str(uuid.uuid4())
            self.current_turn_id = turn_id

            dispatch_resolution, dispatch_error = await resolve_chat_dispatch(
                runtime=self.runtime,
                user_message=user_message,
                requested_agent=requested_agent,
                requested_agents=requested_agents,
                requested_model=user_model,
                dispatch_mode_raw=dispatch_mode_raw,
            )

            if dispatch_error:
                await self.send(
                    {
                        "type": "error",
                        "error": dispatch_error.error,
                        "message": dispatch_error.message,
                    }
                )
                self.current_turn_id = None
                continue

            if dispatch_resolution is None:
                raise RuntimeError("Dispatch resolution returned None without an error")
            await self._execute_dispatch_lifecycle(
                dispatch_id=dispatch_id,
                turn_id=turn_id,
                resolution=dispatch_resolution,
                user_message=user_message,
                user_model=user_model,
                requires_tools=requires_tools,
            )
