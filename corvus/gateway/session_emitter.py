"""SessionEmitter — send/persist/trace methods extracted from ChatSession.

Handles WebSocket delivery, session/run event persistence, and trace
publication.  Pure extraction from chat_session.py — no new behaviour.
"""

from __future__ import annotations

import asyncio
import structlog
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from corvus.gateway.protocol import (
    PERSISTED_SESSION_EVENT_TYPES as _PERSISTED_SESSION_EVENT_TYPES,
    PERSISTED_RUN_EVENT_TYPES as _PERSISTED_RUN_EVENT_TYPES,
    TRACE_EVENT_TYPES as _TRACE_EVENT_TYPES,
)

if TYPE_CHECKING:
    from corvus.gateway.chat_session import TurnContext
    from corvus.gateway.runtime import GatewayRuntime

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers (moved from chat_session.py)
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
# SessionEmitter class
# ---------------------------------------------------------------------------


class SessionEmitter:
    """Send/persist/trace surface extracted from ChatSession.

    Handles three responsibilities:
    1. WebSocket delivery (via ws_send callable)
    2. Session and run event persistence (via runtime.session_mgr)
    3. Trace publication (via runtime.trace_hub)
    """

    def __init__(
        self,
        *,
        runtime: GatewayRuntime,
        ws_send: Callable[[dict], Coroutine[Any, Any, None]] | None,
        session_id: str,
        user: str,
    ) -> None:
        self.runtime = runtime
        self._ws_send_fn = ws_send
        self.session_id = session_id
        self.user = user
        self.send_lock = asyncio.Lock()
        self.current_turn_id: str | None = None

    # ------------------------------------------------------------------
    # Send sub-methods
    # ------------------------------------------------------------------

    async def _ws_send(self, payload: dict) -> None:
        """Send payload over WebSocket under lock."""
        if self._ws_send_fn is None:
            return
        async with self.send_lock:
            await self._ws_send_fn(payload)

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
                "persist_session_event_failed",
                session_id=self.session_id,
                event_type=event_type,
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
                "persist_run_event_failed",
                run_id=run_id,
                event_type=event_type,
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
                "persist_publish_trace_failed",
                session_id=self.session_id,
                event_type=event_type,
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
    # Payload builder and phase/failure/interrupted helpers
    # ------------------------------------------------------------------

    @staticmethod
    def base_payload(
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

    async def emit_phase(
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
        base = self.base_payload(
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

    async def emit_run_failure(
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
        base = self.base_payload(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            session_id=self.session_id,
        )
        await self.emit_phase(
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

    async def emit_run_interrupted(
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
        base = self.base_payload(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            route_payload=route_payload,
            session_id=self.session_id,
        )
        await self.emit_phase(
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
