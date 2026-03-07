"""RunExecutor — extracted execute_agent_run as a standalone async function.

Previously lived as ChatSession.execute_agent_run (~460 lines). Now receives
all dependencies explicitly instead of via ``self``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

from corvus.gateway.acp_executor import execute_acp_run as _execute_acp_run
from corvus.gateway.options import (
    build_backend_options,
    resolve_backend_and_model,
    ui_default_model,
    ui_model_id,
)
from corvus.gateway.workspace_runtime import prepare_agent_workspace

if TYPE_CHECKING:
    from fastapi import WebSocket

    from corvus.gateway.chat_session import TurnContext
    from corvus.gateway.confirm_queue import ConfirmQueue
    from corvus.gateway.runtime import GatewayRuntime
    from corvus.gateway.session_emitter import SessionEmitter
    from corvus.gateway.task_planner import TaskRoute
    from corvus.session import SessionTranscript

logger = logging.getLogger("corvus-gateway")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _preview_summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "\u2026"


def _route_payload(route: TaskRoute, *, route_index: int) -> dict:
    return {
        "task_type": route.task_type,
        "subtask_id": route.subtask_id,
        "skill": route.skill,
        "instruction": route.instruction,
        "route_index": route_index,
    }


# ---------------------------------------------------------------------------
# Main executor function
# ---------------------------------------------------------------------------


async def execute_agent_run(
    *,
    emitter: SessionEmitter,
    runtime: GatewayRuntime,
    turn: TurnContext,
    route: TaskRoute,
    route_index: int,
    transcript: SessionTranscript,
    websocket: WebSocket | None,
    user: str,
    confirm_queue: ConfirmQueue | None,
) -> dict[str, Any]:
    """Execute a single agent run for one route in a dispatch plan.

    This is the extracted body of ``ChatSession.execute_agent_run``.  All
    dependencies that were previously accessed via ``self`` are now passed
    as explicit keyword arguments.
    """
    session_id = emitter.session_id
    send = emitter.send
    emit_phase = emitter.emit_phase
    emit_run_failure = emitter.emit_run_failure
    emit_run_interrupted = emitter.emit_run_interrupted
    base_payload_fn = emitter.base_payload

    agent_name = route.agent
    run_id = str(uuid.uuid4())
    task_id = f"task-{run_id[:8]}"
    transcript.record_agent(agent_name)
    route_pay = _route_payload(route, route_index=route_index)
    run_message = route.prompt
    requested_model = route.requested_model or turn.user_model
    workspace_cwd = prepare_agent_workspace(session_id=session_id, agent_name=agent_name)

    backend_name, active_model = resolve_backend_and_model(
        runtime=runtime,
        agent_name=agent_name,
        requested_model=requested_model,
    )

    # ACP backend: delegate to ACP executor
    if backend_name == "acp":
        return await _execute_acp_run(
            emitter=emitter,
            runtime=runtime,
            turn=turn,
            route=route,
            route_index=route_index,
            transcript=transcript,
            user=user,
            confirm_queue=confirm_queue,
            acp_registry=runtime.acp_registry,
        )

    active_model_id = ui_model_id(backend_name, active_model)
    model_info = runtime.model_router.get_model_info(active_model_id)
    chunk_index = 0
    response_parts: list[str] = []
    assistant_summary = ""
    total_cost = 0.0
    tokens_used = 0
    context_limit = runtime.model_router.get_context_limit(active_model)
    context_pct = 0.0

    # Persist the run row
    try:
        runtime.session_mgr.start_agent_run(
            run_id,
            dispatch_id=turn.dispatch_id,
            session_id=session_id,
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
    await send(
        {
            "type": "routing",
            "agent": agent_name,
            "model": active_model_id,
            **route_pay,
        }
    )
    # run_start event
    await send(
        {
            "type": "run_start",
            "dispatch_id": turn.dispatch_id,
            "run_id": run_id,
            "task_id": task_id,
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "agent": agent_name,
            "backend": backend_name,
            "model": active_model_id,
            "workspace_cwd": str(workspace_cwd),
            "status": "queued",
            **route_pay,
        },
        persist=True,
        run_id=run_id,
        dispatch_id=turn.dispatch_id,
        turn_id=turn.turn_id,
    )
    # task_start event
    await send(
        {
            "type": "task_start",
            "task_id": task_id,
            "agent": agent_name,
            "description": _preview_summary(run_message, limit=120),
            "session_id": session_id,
            "turn_id": turn.turn_id,
            **route_pay,
        },
        persist=True,
        run_id=run_id,
        dispatch_id=turn.dispatch_id,
        turn_id=turn.turn_id,
    )

    try:
        # Phase: routing
        await emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            phase="routing",
            summary="Routing and model validation",
        )
        await runtime.emitter.emit(
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
                runtime=runtime,
                agent_name=agent_name,
                requested_model=None,
            )
            suggested_model = ui_model_id(fallback_backend, fallback_model)
            if suggested_model == active_model_id:
                suggested_model = ui_default_model(runtime)
            await send(
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
                    **route_pay,
                }
            )
            return await emit_run_failure(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_pay,
                error_type="model_capability_mismatch",
                summary="Blocked: selected model cannot execute tool-enabled turn.",
                context_limit=context_limit,
            )

        # Nested closure -- SDK hook callback that enriches payloads with
        # dispatch/run/agent context, then forwards via send().
        async def _run_hook_ws_callback(payload: dict) -> None:
            enriched = dict(payload)
            enriched.setdefault("dispatch_id", turn.dispatch_id)
            enriched.setdefault("run_id", run_id)
            enriched.setdefault("task_id", task_id)
            enriched.setdefault("session_id", session_id)
            enriched.setdefault("turn_id", turn.turn_id)
            enriched.setdefault("agent", agent_name)
            enriched.setdefault("task_type", route.task_type)
            enriched.setdefault("subtask_id", route.subtask_id)
            enriched.setdefault("skill", route.skill)
            enriched.setdefault("instruction", route.instruction)
            enriched.setdefault("route_index", route_index)
            await send(
                enriched,
                persist=True,
                run_id=run_id,
                dispatch_id=turn.dispatch_id,
                turn_id=turn.turn_id,
            )

        client_options = build_backend_options(
            runtime=runtime,
            user=user,
            websocket=websocket,
            backend_name=backend_name,
            active_model=active_model,
            agent_name=agent_name,
            ws_callback=_run_hook_ws_callback,
            allow_secret_access=runtime.break_glass.is_active(
                user=user, session_id=session_id
            ),
            workspace_cwd=workspace_cwd,
            session_id=session_id,
            confirm_queue=confirm_queue,
        )

        async with ClaudeSDKClient(options=client_options) as client:
            try:
                await client.set_model(active_model)
            except Exception as exc:
                logger.warning("Failed to set model '%s': %s", active_model, exc)
                await send(
                    {
                        "type": "error",
                        "error": "model_unavailable",
                        "model": active_model_id,
                        "message": f"Selected model unavailable: {active_model_id}",
                        "agent": agent_name,
                        **route_pay,
                    }
                )
                return await emit_run_failure(
                    turn,
                    run_id=run_id,
                    task_id=task_id,
                    agent=agent_name,
                    route_payload=route_pay,
                    error_type="model_unavailable",
                    summary="Selected model unavailable.",
                    context_limit=context_limit,
                )

            # Phase: planning + executing
            await emit_phase(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_pay,
                phase="planning",
                summary="Preparing execution plan",
            )
            await emit_phase(
                turn,
                run_id=run_id,
                task_id=task_id,
                agent=agent_name,
                route_payload=route_pay,
                phase="executing",
                summary="Agent execution started",
            )

            await client.query(run_message, session_id=session_id)
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
                        await send(
                            {
                                "type": "run_output_chunk",
                                "dispatch_id": turn.dispatch_id,
                                "run_id": run_id,
                                "task_id": task_id,
                                "session_id": session_id,
                                "turn_id": turn.turn_id,
                                "agent": agent_name,
                                "model": active_model_id,
                                "chunk_index": chunk_index,
                                "content": block.text,
                                "final": False,
                                **route_pay,
                            },
                            persist=True,
                            run_id=run_id,
                            dispatch_id=turn.dispatch_id,
                            turn_id=turn.turn_id,
                        )
                        chunk_index += 1
                        await send(
                            {
                                "type": "text",
                                "content": block.text,
                                "agent": agent_name,
                                "model": active_model_id,
                                "run_id": run_id,
                                **route_pay,
                            }
                        )
                        await send(
                            {
                                "type": "task_progress",
                                "task_id": task_id,
                                "agent": agent_name,
                                "status": "streaming",
                                "summary": assistant_summary or "Streaming response...",
                                "session_id": session_id,
                                "turn_id": turn.turn_id,
                                **route_pay,
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
        await emit_phase(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            phase="compacting",
            summary="Compacting and finalizing response",
        )
        # Final output chunk marker
        await send(
            {
                "type": "run_output_chunk",
                "dispatch_id": turn.dispatch_id,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": session_id,
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
                **route_pay,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )

        # Persist assistant response to transcript
        if response_parts:
            assistant_text = " ".join(response_parts)
            transcript.messages.append({"role": "assistant", "content": assistant_text})
            runtime.session_mgr.add_message(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                agent=agent_name,
                model=active_model_id,
            )

        # run_complete (success)
        base = base_payload_fn(
            turn=turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            session_id=session_id,
        )
        await send(
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
        await send(
            {
                "type": "task_complete",
                "task_id": task_id,
                "agent": agent_name,
                "result": "success",
                "summary": assistant_summary or "Completed",
                "cost_usd": total_cost,
                "session_id": session_id,
                "turn_id": turn.turn_id,
                **route_pay,
            },
            persist=True,
            run_id=run_id,
            dispatch_id=turn.dispatch_id,
            turn_id=turn.turn_id,
        )

        runtime.session_mgr.update_agent_run(
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
        return await emit_run_interrupted(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            summary="Interrupted by user",
            cost_usd=total_cost,
            tokens_used=tokens_used,
            context_limit=context_limit,
            context_pct=context_pct,
        )
    except Exception as exc:
        logger.exception("Error processing run agent=%s", agent_name)
        safe_msg = type(exc).__name__
        await send(
            {
                "type": "error",
                "message": f"Internal error: {safe_msg}",
                "agent": agent_name,
                **route_pay,
            }
        )
        return await emit_run_failure(
            turn,
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            route_payload=route_pay,
            error_type=safe_msg,
            summary="Internal error during task execution",
            context_limit=context_limit,
        )
