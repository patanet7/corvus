"""DispatchOrchestrator — dispatch lifecycle management extracted from ChatSession.

Contains the full dispatch lifecycle (setup, execution, summary, cleanup) and
the WebSocket control listener that runs concurrently during active dispatch.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import WebSocketDisconnect

from corvus.config import MAX_PARALLEL_AGENT_RUNS
from corvus.gateway.dispatch_metrics import summarize_dispatch_runs
from corvus.gateway.dispatch_runtime import execute_dispatch_runs
from corvus.gateway.session_emitter import _preview_summary

if TYPE_CHECKING:
    from corvus.gateway.chat_engine import ChatDispatchResolution
    from corvus.gateway.chat_session import ChatSession, TurnContext

logger = logging.getLogger("corvus-gateway")


async def dispatch_control_listener(session: ChatSession) -> None:
    """Listen for interrupt/ping/confirm messages during active dispatch.

    Runs concurrently with dispatch execution. Reads control messages
    from the WebSocket and handles interrupt, ping, confirm_response,
    and dispatch-in-progress rejection for new prompts.
    """
    assert session._current_turn is not None, "dispatch_control_listener requires an active TurnContext"
    assert session.websocket is not None, "dispatch_control_listener requires an active WebSocket"

    turn = session._current_turn

    while not turn.dispatch_interrupted.is_set():
        control_data = await session.websocket.receive_text()
        try:
            control_msg = json.loads(control_data)
        except json.JSONDecodeError:
            await session.send({"type": "error", "message": "Invalid JSON"})
            continue

        control_type = control_msg.get("type")
        if control_type == "interrupt":
            session.runtime.dispatch_controls.request_interrupt(turn.dispatch_id, user=session.user, source="ws")
            logger.info("User interrupted dispatch %s", turn.dispatch_id)
            await session.runtime.emitter.emit("session_interrupt", user=session.user, session_id=session.session_id)
            await session.send(
                {
                    "type": "interrupt_ack",
                    "dispatch_id": turn.dispatch_id,
                    "session_id": session.session_id,
                    "turn_id": turn.turn_id,
                    "status": "interrupting",
                },
                persist=True,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )
            return
        if control_type == "ping":
            await session.send({"type": "pong"})
            continue
        if control_type == "confirm_response":
            call_id = control_msg.get("tool_call_id")
            approved = control_msg.get("approved", False)
            await session.send(
                {
                    "type": "confirm_response",
                    "tool_call_id": call_id,
                    "approved": bool(approved),
                },
                persist=True,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )
            session.confirm_queue.respond(call_id, approved=bool(approved))
            continue
        if control_msg.get("message"):
            await session.send(
                {
                    "type": "error",
                    "error": "dispatch_in_progress",
                    "message": "Dispatch already in progress; wait or interrupt before sending a new prompt.",
                }
            )
            continue
        await session.send({"type": "error", "message": "Unsupported control message while dispatch is active"})


async def execute_dispatch_lifecycle(
    session: ChatSession,
    *,
    dispatch_id: str,
    turn_id: str,
    resolution: ChatDispatchResolution,
    user_message: str,
    user_model: str | None,
    requires_tools: bool,
) -> None:
    """Execute the full dispatch lifecycle for a single user turn.

    Handles: persist dispatch row -> emit events -> record message ->
    create TurnContext -> execute runs -> summarize -> emit completion -> cleanup.
    """
    from corvus.gateway.chat_session import TurnContext

    run_requests = resolution.run_requests
    target_agents = resolution.target_agents
    dispatch_mode = resolution.dispatch_mode
    dispatch_plan = resolution.dispatch_plan

    try:
        session.runtime.session_mgr.create_dispatch(
            dispatch_id,
            session_id=session.session_id,
            turn_id=turn_id,
            user=session.user,
            prompt=user_message,
            dispatch_mode=dispatch_mode,
            target_agents=target_agents,
            status="routing",
        )
    except Exception:
        logger.exception("Failed to persist dispatch row dispatch_id=%s", dispatch_id)

    await session.send(
        {
            "type": "dispatch_start",
            "dispatch_id": dispatch_id,
            "session_id": session.session_id,
            "turn_id": turn_id,
            "dispatch_mode": dispatch_mode,
            "target_agents": target_agents,
            "message": _preview_summary(user_message, limit=140),
        },
        persist=True,
        dispatch_id=dispatch_id,
        turn_id=turn_id,
    )
    await session.send(
        {
            "type": "dispatch_plan",
            "dispatch_id": dispatch_id,
            "session_id": session.session_id,
            "turn_id": turn_id,
            **dispatch_plan.to_payload(),
        },
        persist=True,
        dispatch_id=dispatch_id,
        turn_id=turn_id,
    )
    await session.runtime.emitter.emit(
        "dispatch_plan_resolved",
        dispatch_id=dispatch_id,
        session_id=session.session_id,
        turn_id=turn_id,
        task_type=dispatch_plan.task_type,
        decomposed=dispatch_plan.decomposed,
        strategy=dispatch_plan.strategy,
        route_count=len(run_requests),
        target_agents=target_agents,
    )

    session.transcript.messages.append({"role": "user", "content": user_message})
    session.runtime.session_mgr.add_message(
        session_id=session.session_id,
        role="user",
        content=user_message,
        agent=run_requests[0].agent if len(run_requests) == 1 else "general",
        model=user_model,
    )
    dispatch_interrupted = asyncio.Event()
    session.runtime.dispatch_controls.register(
        dispatch_id=dispatch_id,
        session_id=session.session_id,
        user=session.user,
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
    session._current_turn = turn

    control_listener_task: asyncio.Task[None] | None = None
    try:
        control_listener_task = asyncio.create_task(dispatch_control_listener(session))
        run_results = await execute_dispatch_runs(
            dispatch_mode=dispatch_mode,
            run_requests=run_requests,
            max_parallel_agent_runs=MAX_PARALLEL_AGENT_RUNS,
            execute_run=session.execute_agent_run,
            logger=logger,
            dispatch_interrupted=dispatch_interrupted,
        )

        summary = summarize_dispatch_runs(run_results, interrupted=dispatch_interrupted.is_set())
        session.runtime.session_mgr.update_dispatch(
            dispatch_id,
            status=summary.status,
            error=summary.error,
            completed_at=datetime.now(UTC),
        )

        await session.send(
            {
                "type": "dispatch_complete",
                "dispatch_id": dispatch_id,
                "session_id": session.session_id,
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
        await session.runtime.emitter.emit(
            "dispatch_completed",
            dispatch_id=dispatch_id,
            session_id=session.session_id,
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
        await session.send(
            {
                "type": "done",
                "session_id": session.session_id,
                "cost_usd": summary.cost_usd,
                "tokens_used": summary.tokens_used,
                "context_limit": summary.max_context_limit,
                "context_pct": summary.max_context_pct,
            }
        )
    except Exception:
        logger.exception("Dispatch failed dispatch_id=%s", dispatch_id)
        session.runtime.session_mgr.update_dispatch(
            dispatch_id,
            status="error",
            error="dispatch_execution_error",
            completed_at=datetime.now(UTC),
        )
        await session.send(
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
        session.runtime.dispatch_controls.unregister(dispatch_id)
        session._current_turn = None
        session.confirm_queue.cancel_all()
        session.current_turn_id = None
