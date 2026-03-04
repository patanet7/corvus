"""ChatSession class — WebSocket chat lifecycle extracted from closure soup.

Converts the deeply nested closures in claw/api/chat.py into a class with
explicit instance state. Session-lifetime state lives on the instance;
per-turn state is scoped via TurnContext.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
from fastapi import WebSocket, WebSocketDisconnect

from corvus.config import MAX_PARALLEL_AGENT_RUNS
from corvus.gateway.chat_engine import ChatDispatchResolution, resolve_chat_dispatch, resolve_default_agent
from corvus.gateway.dispatch_metrics import summarize_dispatch_runs
from corvus.gateway.dispatch_runtime import execute_dispatch_runs
from corvus.gateway.options import (
    any_llm_configured,
    build_backend_options,
    resolve_backend_and_model,
    ui_default_model,
    ui_model_id,
)
from corvus.gateway.runtime import GatewayRuntime
from corvus.gateway.task_planner import TaskRoute
from corvus.gateway.workspace_runtime import prepare_agent_workspace
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


# ---------------------------------------------------------------------------
# Event type sets (copied verbatim from claw/api/chat.py lines 38-71)
# ---------------------------------------------------------------------------

_PERSISTED_SESSION_EVENT_TYPES = {
    "dispatch_start",
    "dispatch_plan",
    "dispatch_complete",
    "run_start",
    "run_phase",
    "run_output_chunk",
    "run_complete",
    "task_start",
    "task_progress",
    "task_complete",
    "tool_start",
    "tool_result",
    "tool_permission_decision",
    "confirm_request",
    "confirm_response",
    "interrupt_ack",
}

_PERSISTED_RUN_EVENT_TYPES = {
    "run_start",
    "run_phase",
    "run_output_chunk",
    "run_complete",
    "tool_start",
    "tool_result",
    "tool_permission_decision",
    "confirm_request",
    "confirm_response",
}

_TRACE_EVENT_TYPES = _PERSISTED_SESSION_EVENT_TYPES | {
    "routing",
    "agent_status",
    "error",
}


# ---------------------------------------------------------------------------
# Module-level helpers (moved from claw/api/chat.py lines 88-131)
# ---------------------------------------------------------------------------


def _preview_summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "\u2026"


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


def _trace_source_app(event_type: str, payload: dict) -> str:
    if agent := _optional_str(payload.get("agent")):
        return agent
    if event_type in {"dispatch_start", "dispatch_plan", "dispatch_complete", "routing"}:
        return "router"
    return "gateway"


def _trace_summary(event_type: str, payload: dict) -> str | None:
    if summary := _optional_str(payload.get("summary")):
        return _preview_summary(summary, limit=220)
    if event_type == "run_output_chunk":
        if content := _optional_str(payload.get("content")):
            return _preview_summary(content, limit=220)
        if payload.get("final") is True:
            return "Final output marker"
    if message := _optional_str(payload.get("message")):
        return _preview_summary(message, limit=220)
    if event_type == "tool_start":
        if tool := _optional_str(payload.get("tool")):
            return f"Tool start: {tool}"
    if event_type == "tool_result":
        status = _optional_str(payload.get("status")) or "success"
        return f"Tool result ({status})"
    if event_type == "tool_permission_decision":
        state = _optional_str(payload.get("state")) or "deny"
        tool = _optional_str(payload.get("tool")) or "tool"
        return f"Permission {state}: {tool}"
    if event_type == "confirm_request":
        if tool := _optional_str(payload.get("tool")):
            return f"Confirm request: {tool}"
    return None


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
        self.send_lock = asyncio.Lock()
        self.current_turn_id: str | None = None
        self._current_turn: TurnContext | None = None
        self.transcript = SessionTranscript(
            user=user,
            session_id=session_id,
            messages=[],
        )

    # ------------------------------------------------------------------
    # Send sub-methods (decomposed from the monolithic _send closure)
    # ------------------------------------------------------------------

    async def _ws_send(self, payload: dict) -> None:
        """Send payload over WebSocket under lock."""
        if self.websocket is None:
            return
        async with self.send_lock:
            await self.websocket.send_json(payload)

    def _persist_session_event(
        self,
        *,
        event_type: str,
        payload: dict,
        turn_id: str | None,
    ) -> None:
        """Persist to session events table."""
        try:
            self.runtime.session_mgr.add_event(
                session_id=self.session_id,
                turn_id=turn_id or self.current_turn_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "Failed to persist session event: session_id=%s type=%s",
                self.session_id,
                event_type,
            )

    def _persist_run_event(
        self,
        *,
        run_id: str,
        dispatch_id: str,
        event_type: str,
        payload: dict,
        turn_id: str | None,
    ) -> None:
        """Persist to run events table."""
        try:
            self.runtime.session_mgr.add_run_event(
                run_id,
                dispatch_id=dispatch_id,
                session_id=self.session_id,
                turn_id=turn_id or self.current_turn_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "Failed to persist run event: run_id=%s type=%s",
                run_id,
                event_type,
            )

    async def _publish_trace(
        self,
        *,
        event_type: str,
        payload: dict,
        dispatch_id: str | None,
        run_id: str | None,
        turn_id: str | None,
    ) -> None:
        """Publish to TraceHub for live observability."""
        trace_dispatch_id = dispatch_id or _optional_str(payload.get("dispatch_id"))
        trace_run_id = run_id or _optional_str(payload.get("run_id"))
        trace_turn_id = turn_id or self.current_turn_id or _optional_str(payload.get("turn_id"))
        try:
            trace_row = self.runtime.session_mgr.add_trace_event(
                source_app=_trace_source_app(event_type, payload),
                session_id=self.session_id,
                dispatch_id=trace_dispatch_id,
                run_id=trace_run_id,
                turn_id=trace_turn_id,
                hook_event_type=event_type,
                payload=payload,
                summary=_trace_summary(event_type, payload),
                model_name=_optional_str(payload.get("model")),
            )
            await self.runtime.trace_hub.publish(user=self.user, event=trace_row)
        except Exception:
            logger.exception(
                "Failed to persist/publish trace event: session_id=%s type=%s",
                self.session_id,
                event_type,
            )

    async def send(
        self,
        payload: dict,
        *,
        persist: bool = False,
        run_id: str | None = None,
        dispatch_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        """Orchestrate: ws_send + optional persist + optional trace."""
        await self._ws_send(payload)
        event_type = str(payload.get("type", ""))
        if persist and event_type in _PERSISTED_SESSION_EVENT_TYPES:
            self._persist_session_event(
                event_type=event_type,
                payload=payload,
                turn_id=turn_id,
            )
        if run_id and dispatch_id and event_type in _PERSISTED_RUN_EVENT_TYPES and persist:
            self._persist_run_event(
                run_id=run_id,
                dispatch_id=dispatch_id,
                event_type=event_type,
                payload=payload,
                turn_id=turn_id,
            )
        should_trace = event_type in _TRACE_EVENT_TYPES and (
            persist or event_type in {"routing", "agent_status", "error"}
        )
        if should_trace:
            await self._publish_trace(
                event_type=event_type,
                payload=payload,
                dispatch_id=dispatch_id,
                run_id=run_id,
                turn_id=turn_id,
            )

    # ------------------------------------------------------------------
    # Payload builder and run failure helper
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
        return {
            "dispatch_id": turn.dispatch_id,
            "run_id": run_id,
            "task_id": task_id,
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "agent": agent,
            **route_payload,
        }

    async def _emit_phase(
        self,
        turn: TurnContext,
        *,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        phase: str,
        summary: str,
    ) -> None:
        """Emit run_phase + optional task_progress events."""
        base = self._base_payload(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            session_id=self.session_id,
        )
        phase_status = "streaming" if phase == "executing" else "error" if phase == "error" else "thinking"
        await self.send(
            {"type": "run_phase", **base, "phase": phase, "summary": summary},
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        if phase not in {"done", "error", "interrupted"}:
            await self.send(
                {
                    "type": "task_progress",
                    "task_id": task_id,
                    "agent": agent,
                    "status": phase_status,
                    "summary": summary,
                    "session_id": self.session_id,
                    "turn_id": turn.turn_id,
                    **route_payload,
                },
                persist=True,
                run_id=run_id,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )

    async def _emit_run_failure(
        self,
        turn: TurnContext,
        *,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        error_type: str,
        summary: str,
        context_limit: int,
    ) -> dict:
        """Consolidated error exit: emit events, update run record, return error dict."""
        base = self._base_payload(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            session_id=self.session_id,
        )
        await self._emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            phase="error",
            summary=summary,
        )
        await self.send(
            {
                "type": "run_complete",
                **base,
                "result": "error",
                "summary": summary,
                "cost_usd": 0.0,
                "tokens_used": 0,
                "context_limit": context_limit,
                "context_pct": 0.0,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        await self.send(
            {
                "type": "task_complete",
                "task_id": task_id,
                "agent": agent,
                "result": "error",
                "summary": summary,
                "cost_usd": 0.0,
                "session_id": self.session_id,
                "turn_id": turn.turn_id,
                **route_payload,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        self.runtime.session_mgr.update_agent_run(
            run_id,
            status="error",
            summary=summary,
            error=error_type,
            completed_at=datetime.now(UTC),
        )
        return {"result": "error", "cost_usd": 0.0, "tokens_used": 0, "context_pct": 0.0}

    async def _emit_run_interrupted(
        self,
        turn: TurnContext,
        *,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        summary: str,
        cost_usd: float,
        tokens_used: int,
        context_limit: int,
        context_pct: float,
    ) -> dict:
        """Consolidated interrupted exit: emit events, update run record, return result dict."""
        base = self._base_payload(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            session_id=self.session_id,
        )
        await self._emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            phase="interrupted",
            summary=summary,
        )
        await self.send(
            {
                "type": "run_complete",
                **base,
                "result": "interrupted",
                "summary": summary,
                "cost_usd": cost_usd,
                "tokens_used": tokens_used,
                "context_limit": context_limit,
                "context_pct": context_pct,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        await self.send(
            {
                "type": "task_complete",
                "task_id": task_id,
                "agent": agent,
                "result": "interrupted",
                "summary": summary,
                "cost_usd": cost_usd,
                "session_id": self.session_id,
                "turn_id": turn.turn_id,
                **route_payload,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        self.runtime.session_mgr.update_agent_run(
            run_id,
            status="interrupted",
            summary=summary,
            completed_at=datetime.now(UTC),
        )
        return {
            "result": "interrupted",
            "cost_usd": cost_usd,
            "tokens_used": tokens_used,
            "context_pct": context_pct,
            "context_limit": context_limit,
        }

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
    # execute_agent_run — ported from claw/api/chat.py lines 472-1057
    # ------------------------------------------------------------------

    async def execute_agent_run(self, route: TaskRoute, *, route_index: int) -> dict:
        """Execute a single agent run for one route in a dispatch plan.

        Matches the RunExecutor protocol. Uses ``self._current_turn``
        (TurnContext) for per-turn state instead of closure variables.
        """
        turn = self._current_turn
        assert turn is not None, "execute_agent_run requires an active TurnContext"

        agent_name = route.agent
        run_id = str(uuid.uuid4())
        task_id = f"task-{run_id[:8]}"
        self.transcript.record_agent(agent_name)
        route_payload = self._route_payload(route, route_index=route_index)
        run_message = route.prompt
        requested_model = route.requested_model or turn.user_model
        workspace_cwd = prepare_agent_workspace(session_id=self.session_id, agent_name=agent_name)

        backend_name, active_model = resolve_backend_and_model(
            runtime=self.runtime,
            agent_name=agent_name,
            requested_model=requested_model,
        )
        active_model_id = ui_model_id(backend_name, active_model)
        model_info = self.runtime.model_router.get_model_info(active_model_id)
        chunk_index = 0
        response_parts: list[str] = []
        assistant_summary = ""
        total_cost = 0.0
        tokens_used = 0
        context_limit = self.runtime.model_router.get_context_limit(active_model)
        context_pct = 0.0

        # Persist the run row
        try:
            self.runtime.session_mgr.start_agent_run(
                run_id,
                dispatch_id=turn.dispatch_id,
                session_id=self.session_id,
                turn_id=turn.turn_id,
                agent=agent_name,
                backend=backend_name,
                model=active_model_id,
                task_type=route.task_type,
                subtask_id=route.subtask_id,
                skill=route.skill,
                status="queued",
            )
        except Exception:
            logger.exception("Failed to persist run row run_id=%s", run_id)

        # routing event (non-persisted)
        await self.send(
            {
                "type": "routing",
                "agent": agent_name,
                "model": active_model_id,
                **route_payload,
            }
        )
        # run_start event
        await self.send(
            {
                "type": "run_start",
                "dispatch_id": turn.dispatch_id,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": self.session_id,
                "turn_id": turn.turn_id,
                "agent": agent_name,
                "backend": backend_name,
                "model": active_model_id,
                "workspace_cwd": str(workspace_cwd),
                "status": "queued",
                **route_payload,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )
        # task_start event
        await self.send(
            {
                "type": "task_start",
                "task_id": task_id,
                "agent": agent_name,
                "description": _preview_summary(run_message, limit=120),
                "session_id": self.session_id,
                "turn_id": turn.turn_id,
                **route_payload,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )

        try:
            # Phase: routing
            await self._emit_phase(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_payload,
                phase="routing",
                summary="Routing and model validation",
            )
            await self.runtime.emitter.emit(
                "routing_decision",
                agent=agent_name,
                backend=backend_name,
                source="websocket",
                query_preview=run_message[:200],
                task_type=route.task_type,
                subtask_id=route.subtask_id,
                skill=route.skill,
            )
            if turn.dispatch_interrupted.is_set():
                raise asyncio.CancelledError

            # Model capability mismatch check
            if turn.requires_tools and model_info and not model_info.supports_tools:
                fallback_backend, fallback_model = resolve_backend_and_model(
                    runtime=self.runtime,
                    agent_name=agent_name,
                    requested_model=None,
                )
                suggested_model = ui_model_id(fallback_backend, fallback_model)
                if suggested_model == active_model_id:
                    suggested_model = ui_default_model(self.runtime)
                await self.send(
                    {
                        "type": "error",
                        "error": "model_capability_mismatch",
                        "model": active_model_id,
                        "capability": "tools",
                        "suggested_model": suggested_model,
                        "message": (
                            f"Model `{active_model_id}` does not support tool-enabled turns. "
                            f"Switch to `{suggested_model}` and retry."
                        ),
                        "agent": agent_name,
                        **route_payload,
                    }
                )
                return await self._emit_run_failure(
                    turn,
                    run_id=run_id,
                    task_id=task_id,
                    agent=agent_name,
                    route_payload=route_payload,
                    error_type="model_capability_mismatch",
                    summary="Blocked: selected model cannot execute tool-enabled turn.",
                    context_limit=context_limit,
                )

            backend_env = self.runtime.client_pool.build_env(backend_name)

            # Nested closure — SDK hook callback that enriches payloads with
            # dispatch/run/agent context, then forwards via self.send().
            async def _run_hook_ws_callback(payload: dict) -> None:
                enriched = dict(payload)
                enriched.setdefault("dispatch_id", turn.dispatch_id)
                enriched.setdefault("run_id", run_id)
                enriched.setdefault("task_id", task_id)
                enriched.setdefault("session_id", self.session_id)
                enriched.setdefault("turn_id", turn.turn_id)
                enriched.setdefault("agent", agent_name)
                enriched.setdefault("task_type", route.task_type)
                enriched.setdefault("subtask_id", route.subtask_id)
                enriched.setdefault("skill", route.skill)
                enriched.setdefault("instruction", route.instruction)
                enriched.setdefault("route_index", route_index)
                await self.send(
                    enriched,
                    persist=True,
                    run_id=run_id,
                    dispatch_id=turn.dispatch_id,
                    turn_id=turn.turn_id,
                )

            client_options = build_backend_options(
                runtime=self.runtime,
                user=self.user,
                websocket=self.websocket,
                backend_name=backend_name,
                backend_env=backend_env,
                active_model=active_model,
                agent_name=agent_name,
                ws_callback=_run_hook_ws_callback,
                allow_secret_access=self.runtime.break_glass.is_active(
                    user=self.user, session_id=self.session_id
                ),
                workspace_cwd=workspace_cwd,
                session_id=self.session_id,
            )

            async with ClaudeSDKClient(options=client_options) as client:
                try:
                    await client.set_model(active_model)
                except Exception as exc:
                    logger.warning("Failed to set model '%s': %s", active_model, exc)
                    await self.send(
                        {
                            "type": "error",
                            "error": "model_unavailable",
                            "model": active_model_id,
                            "message": f"Selected model unavailable: {active_model_id}",
                            "agent": agent_name,
                            **route_payload,
                        }
                    )
                    return await self._emit_run_failure(
                        turn,
                        run_id=run_id,
                        task_id=task_id,
                        agent=agent_name,
                        route_payload=route_payload,
                        error_type="model_unavailable",
                        summary="Selected model unavailable.",
                        context_limit=context_limit,
                    )

                # Phase: planning + executing
                await self._emit_phase(
                    turn,
                    run_id=run_id,
                    task_id=task_id,
                    agent=agent_name,
                    route_payload=route_payload,
                    phase="planning",
                    summary="Preparing execution plan",
                )
                await self._emit_phase(
                    turn,
                    run_id=run_id,
                    task_id=task_id,
                    agent=agent_name,
                    route_payload=route_payload,
                    phase="executing",
                    summary="Agent execution started",
                )

                await client.query(run_message, session_id=self.session_id)
                async for sdk_message in client.receive_response():
                    if turn.dispatch_interrupted.is_set():
                        raise asyncio.CancelledError
                    if isinstance(sdk_message, AssistantMessage):
                        for block in sdk_message.content:
                            if not isinstance(block, TextBlock):
                                continue
                            response_parts.append(block.text)
                            assistant_summary = _preview_summary(
                                " ".join(response_parts), limit=140
                            )
                            await self.send(
                                {
                                    "type": "run_output_chunk",
                                    "dispatch_id": turn.dispatch_id,
                                    "run_id": run_id,
                                    "task_id": task_id,
                                    "session_id": self.session_id,
                                    "turn_id": turn.turn_id,
                                    "agent": agent_name,
                                    "model": active_model_id,
                                    "chunk_index": chunk_index,
                                    "content": block.text,
                                    "final": False,
                                    **route_payload,
                                },
                                persist=True,
                                run_id=run_id,
                                dispatch_id=turn.dispatch_id,
                                turn_id=turn.turn_id,
                            )
                            chunk_index += 1
                            await self.send(
                                {
                                    "type": "text",
                                    "content": block.text,
                                    "agent": agent_name,
                                    "model": active_model_id,
                                    "run_id": run_id,
                                    **route_payload,
                                }
                            )
                            await self.send(
                                {
                                    "type": "task_progress",
                                    "task_id": task_id,
                                    "agent": agent_name,
                                    "status": "streaming",
                                    "summary": assistant_summary or "Streaming response...",
                                    "session_id": self.session_id,
                                    "turn_id": turn.turn_id,
                                    **route_payload,
                                },
                                persist=True,
                                run_id=run_id,
                                dispatch_id=turn.dispatch_id,
                                turn_id=turn.turn_id,
                            )
                    elif isinstance(sdk_message, ResultMessage):
                        tokens_used = int(getattr(sdk_message, "total_input_tokens", 0)) + int(
                            getattr(sdk_message, "total_output_tokens", 0),
                        )
                        total_cost = float(getattr(sdk_message, "total_cost_usd", 0.0))
                        context_pct = (
                            round((tokens_used / context_limit) * 100, 1)
                            if context_limit > 0
                            else 0.0
                        )

            # Phase: compacting
            await self._emit_phase(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_payload,
                phase="compacting",
                summary="Compacting and finalizing response",
            )
            # Final output chunk marker
            await self.send(
                {
                    "type": "run_output_chunk",
                    "dispatch_id": turn.dispatch_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "session_id": self.session_id,
                    "turn_id": turn.turn_id,
                    "agent": agent_name,
                    "model": active_model_id,
                    "chunk_index": chunk_index,
                    "content": "",
                    "final": True,
                    "tokens_used": tokens_used,
                    "cost_usd": total_cost,
                    "context_limit": context_limit,
                    "context_pct": context_pct,
                    **route_payload,
                },
                persist=True,
                run_id=run_id,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )

            # Persist assistant response to transcript
            if response_parts:
                assistant_text = " ".join(response_parts)
                self.transcript.messages.append({"role": "assistant", "content": assistant_text})
                self.runtime.session_mgr.add_message(
                    session_id=self.session_id,
                    role="assistant",
                    content=assistant_text,
                    agent=agent_name,
                    model=active_model_id,
                )

            # run_complete (success)
            base = self._base_payload(
                turn=turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_payload,
                session_id=self.session_id,
            )
            await self.send(
                {
                    "type": "run_complete",
                    **base,
                    "result": "success",
                    "summary": assistant_summary or "Completed",
                    "cost_usd": total_cost,
                    "tokens_used": tokens_used,
                    "context_limit": context_limit,
                    "context_pct": context_pct,
                },
                persist=True,
                run_id=run_id,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )
            # task_complete (success)
            await self.send(
                {
                    "type": "task_complete",
                    "task_id": task_id,
                    "agent": agent_name,
                    "result": "success",
                    "summary": assistant_summary or "Completed",
                    "cost_usd": total_cost,
                    "session_id": self.session_id,
                    "turn_id": turn.turn_id,
                    **route_payload,
                },
                persist=True,
                run_id=run_id,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )

            self.runtime.session_mgr.update_agent_run(
                run_id,
                status="done",
                summary=assistant_summary or "Completed",
                cost_usd=total_cost,
                tokens_used=tokens_used,
                context_limit=context_limit,
                context_pct=context_pct,
                completed_at=datetime.now(UTC),
            )
            return {
                "result": "success",
                "cost_usd": total_cost,
                "tokens_used": tokens_used,
                "context_pct": context_pct,
                "context_limit": context_limit,
            }
        except asyncio.CancelledError:
            return await self._emit_run_interrupted(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_payload,
                summary="Interrupted by user",
                cost_usd=total_cost,
                tokens_used=tokens_used,
                context_limit=context_limit,
                context_pct=context_pct,
            )
        except Exception as exc:
            logger.exception("Error processing run agent=%s", agent_name)
            safe_msg = type(exc).__name__
            await self.send(
                {
                    "type": "error",
                    "message": f"Internal error: {safe_msg}",
                    "agent": agent_name,
                    **route_payload,
                }
            )
            return await self._emit_run_failure(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_payload,
                error_type=safe_msg,
                summary="Internal error during task execution",
                context_limit=context_limit,
            )

    # ------------------------------------------------------------------
    # dispatch_control_listener — ported from claw/api/chat.py lines 1059-1112
    # ------------------------------------------------------------------

    async def dispatch_control_listener(self) -> None:
        """Listen for interrupt/ping/confirm messages during active dispatch.

        Runs concurrently with dispatch execution. Reads control messages
        from the WebSocket and handles interrupt, ping, confirm_response,
        and dispatch-in-progress rejection for new prompts.
        """
        assert self._current_turn is not None, "dispatch_control_listener requires an active TurnContext"
        assert self.websocket is not None, "dispatch_control_listener requires an active WebSocket"

        turn = self._current_turn

        while not turn.dispatch_interrupted.is_set():
            control_data = await self.websocket.receive_text()
            try:
                control_msg = json.loads(control_data)
            except json.JSONDecodeError:
                await self.send({"type": "error", "message": "Invalid JSON"})
                continue

            control_type = control_msg.get("type")
            if control_type == "interrupt":
                self.runtime.dispatch_controls.request_interrupt(turn.dispatch_id, user=self.user, source="ws")
                logger.info("User interrupted dispatch %s", turn.dispatch_id)
                await self.runtime.emitter.emit("session_interrupt", user=self.user, session_id=self.session_id)
                await self.send(
                    {
                        "type": "interrupt_ack",
                        "dispatch_id": turn.dispatch_id,
                        "session_id": self.session_id,
                        "turn_id": turn.turn_id,
                        "status": "interrupting",
                    },
                    persist=True,
                    dispatch_id=turn.dispatch_id,
                    turn_id=turn.turn_id,
                )
                return
            if control_type == "ping":
                await self.send({"type": "pong"})
                continue
            if control_type == "confirm_response":
                call_id = control_msg.get("tool_call_id")
                approved = control_msg.get("approved", False)
                await self.send(
                    {
                        "type": "confirm_response",
                        "tool_call_id": call_id,
                        "approved": bool(approved),
                    },
                    persist=True,
                    dispatch_id=turn.dispatch_id,
                    turn_id=turn.turn_id,
                )
                continue
            if control_msg.get("message"):
                await self.send(
                    {
                        "type": "error",
                        "error": "dispatch_in_progress",
                        "message": "Dispatch already in progress; wait or interrupt before sending a new prompt.",
                    }
                )
                continue
            await self.send({"type": "error", "message": "Unsupported control message while dispatch is active"})

    # ------------------------------------------------------------------
    # _degraded_message_loop — ported from claw/api/chat.py lines 133-155
    # ------------------------------------------------------------------

    async def _degraded_message_loop(self) -> None:
        """Run heartbeat/error loop when no LLM backend is configured."""
        assert self.websocket is not None, "_degraded_message_loop requires an active WebSocket"

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
        """Execute the full dispatch lifecycle for a single user turn.

        Handles: persist dispatch row → emit events → record message →
        create TurnContext → execute runs → summarize → emit completion → cleanup.
        """
        run_requests = resolution.run_requests
        target_agents = resolution.target_agents
        dispatch_mode = resolution.dispatch_mode
        dispatch_plan = resolution.dispatch_plan

        try:
            self.runtime.session_mgr.create_dispatch(
                dispatch_id,
                session_id=self.session_id,
                turn_id=turn_id,
                user=self.user,
                prompt=user_message,
                dispatch_mode=dispatch_mode,
                target_agents=target_agents,
                status="routing",
            )
        except Exception:
            logger.exception("Failed to persist dispatch row dispatch_id=%s", dispatch_id)

        await self.send(
            {
                "type": "dispatch_start",
                "dispatch_id": dispatch_id,
                "session_id": self.session_id,
                "turn_id": turn_id,
                "dispatch_mode": dispatch_mode,
                "target_agents": target_agents,
                "message": _preview_summary(user_message, limit=140),
            },
            persist=True,
            dispatch_id=dispatch_id,
            turn_id=turn_id,
        )
        await self.send(
            {
                "type": "dispatch_plan",
                "dispatch_id": dispatch_id,
                "session_id": self.session_id,
                "turn_id": turn_id,
                **dispatch_plan.to_payload(),
            },
            persist=True,
            dispatch_id=dispatch_id,
            turn_id=turn_id,
        )
        await self.runtime.emitter.emit(
            "dispatch_plan_resolved",
            dispatch_id=dispatch_id,
            session_id=self.session_id,
            turn_id=turn_id,
            task_type=dispatch_plan.task_type,
            decomposed=dispatch_plan.decomposed,
            strategy=dispatch_plan.strategy,
            route_count=len(run_requests),
            target_agents=target_agents,
        )

        self.transcript.messages.append({"role": "user", "content": user_message})
        self.runtime.session_mgr.add_message(
            session_id=self.session_id,
            role="user",
            content=user_message,
            agent=run_requests[0].agent if len(run_requests) == 1 else "general",
            model=user_model,
        )
        dispatch_interrupted = asyncio.Event()
        self.runtime.dispatch_controls.register(
            dispatch_id=dispatch_id,
            session_id=self.session_id,
            user=self.user,
            turn_id=turn_id,
            interrupt_event=dispatch_interrupted,
        )

        turn = TurnContext(
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            dispatch_interrupted=dispatch_interrupted,
            user_model=user_model,
            requires_tools=requires_tools,
        )
        self._current_turn = turn

        control_listener_task: asyncio.Task[None] | None = None
        try:
            control_listener_task = asyncio.create_task(self.dispatch_control_listener())
            run_results = await execute_dispatch_runs(
                dispatch_mode=dispatch_mode,
                run_requests=run_requests,
                max_parallel_agent_runs=MAX_PARALLEL_AGENT_RUNS,
                execute_run=self.execute_agent_run,
                logger=logger,
                dispatch_interrupted=dispatch_interrupted,
            )

            summary = summarize_dispatch_runs(run_results, interrupted=dispatch_interrupted.is_set())
            self.runtime.session_mgr.update_dispatch(
                dispatch_id,
                status=summary.status,
                error=summary.error,
                completed_at=datetime.now(UTC),
            )

            await self.send(
                {
                    "type": "dispatch_complete",
                    "dispatch_id": dispatch_id,
                    "session_id": self.session_id,
                    "turn_id": turn_id,
                    "status": summary.status,
                    "task_type": dispatch_plan.task_type,
                    "decomposed": dispatch_plan.decomposed,
                    "strategy": dispatch_plan.strategy,
                    "target_agents": target_agents,
                    "total_runs": summary.total_runs,
                    "success_count": summary.success_count,
                    "error_count": summary.error_count,
                    "interrupted_count": summary.interrupted_count,
                    "cost_usd": summary.cost_usd,
                    "max_parallel": MAX_PARALLEL_AGENT_RUNS,
                },
                persist=True,
                dispatch_id=dispatch_id,
                turn_id=turn_id,
            )
            await self.runtime.emitter.emit(
                "dispatch_completed",
                dispatch_id=dispatch_id,
                session_id=self.session_id,
                turn_id=turn_id,
                status=summary.status,
                task_type=dispatch_plan.task_type,
                decomposed=dispatch_plan.decomposed,
                strategy=dispatch_plan.strategy,
                total_runs=summary.total_runs,
                success_count=summary.success_count,
                error_count=summary.error_count,
                interrupted_count=summary.interrupted_count,
                cost_usd=summary.cost_usd,
                tokens_used=summary.tokens_used,
            )
            await self.send(
                {
                    "type": "done",
                    "session_id": self.session_id,
                    "cost_usd": summary.cost_usd,
                    "tokens_used": summary.tokens_used,
                    "context_limit": summary.max_context_limit,
                    "context_pct": summary.max_context_pct,
                }
            )
        except Exception:
            logger.exception("Dispatch failed dispatch_id=%s", dispatch_id)
            self.runtime.session_mgr.update_dispatch(
                dispatch_id,
                status="error",
                error="dispatch_execution_error",
                completed_at=datetime.now(UTC),
            )
            await self.send(
                {
                    "type": "error",
                    "message": "Internal error: dispatch_execution_error",
                }
            )
        finally:
            if control_listener_task is not None:
                if not control_listener_task.done():
                    control_listener_task.cancel()
                try:
                    await control_listener_task
                except asyncio.CancelledError:
                    pass
                except WebSocketDisconnect:
                    raise
                except Exception:
                    logger.exception("Dispatch control listener failed")
            self.runtime.dispatch_controls.unregister(dispatch_id)
            self._current_turn = None
            self.current_turn_id = None

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
        assert self.websocket is not None, "run() requires an active WebSocket"

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
                # TODO: Wire to SDK confirm gate when supported
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

            assert dispatch_resolution is not None
            await self._execute_dispatch_lifecycle(
                dispatch_id=dispatch_id,
                turn_id=turn_id,
                resolution=dispatch_resolution,
                user_message=user_message,
                user_model=user_model,
                requires_tools=requires_tools,
            )
