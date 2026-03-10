"""Planner-driven background dispatch execution for non-WebSocket callers.

This module is used by webhook/scheduler paths to run the same hierarchical
multi-agent dispatch flow as chat, while persisting dispatch/run/session events.
"""

from __future__ import annotations

import asyncio
import structlog
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from corvus.gateway.dispatch_metrics import summarize_dispatch_runs
from corvus.gateway.dispatch_runtime import execute_dispatch_runs
from corvus.gateway.options import build_backend_options, resolve_backend_and_model, ui_model_id
from corvus.gateway.runtime import GatewayRuntime
from corvus.gateway.stream_processor import RunContext, StreamProcessor
from corvus.gateway.task_planner import TaskRoute
from corvus.gateway.workspace_runtime import cleanup_session_workspaces, prepare_agent_workspace

logger = structlog.get_logger(__name__)


class DispatchValidationError(ValueError):
    """Raised when the incoming dispatch request cannot be resolved safely."""


@dataclass(slots=True)
class DispatchExecutionSummary:
    """Outcome summary for a completed background dispatch."""

    status: str
    run_count: int
    success_count: int
    error_count: int
    interrupted_count: int
    tokens_used: int
    cost_usd: float


def _resolve_requested_agents(
    *,
    initial_agent: str,
    target_agents: list[str] | None,
    enabled_agents: list[str],
) -> list[str]:
    """Resolve/validate explicit requested agents against enabled agents."""
    enabled_lookup = {name.lower(): name for name in enabled_agents}

    default_agent = "general" if "general" in enabled_agents else (enabled_agents[0] if enabled_agents else "")
    if not default_agent:
        raise DispatchValidationError("No enabled agents available")

    requested: list[str] = []
    if target_agents:
        for raw in target_agents:
            token = str(raw).strip().lower()
            if token in {"all", "@all"}:
                requested.extend(enabled_agents)
                continue
            if token not in enabled_lookup:
                raise DispatchValidationError(f"Unknown or disabled agent: {token}")
            requested.append(enabled_lookup[token])
    else:
        token = str(initial_agent).strip().lower()
        if token in enabled_lookup:
            requested = [enabled_lookup[token]]
        elif token in {"all", "@all"}:
            requested = list(enabled_agents)
        else:
            requested = [default_agent]

    # Preserve order, remove duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for name in requested:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped or [default_agent]


async def execute_planned_background_dispatch(
    *,
    runtime: GatewayRuntime,
    session_owner: str,
    prompt: str,
    initial_agent: str,
    webhook_type: str,
    target_agents: list[str] | None,
    dispatch_mode: str,
    requested_model: str | None,
    source: str,
    max_parallel_agent_runs: int,
) -> DispatchExecutionSummary:
    """Execute planner-derived multi-agent dispatch for non-WS paths."""
    enabled_agents = [item.name for item in runtime.agents_hub.list_agents() if item.enabled]
    requested_agents = _resolve_requested_agents(
        initial_agent=initial_agent,
        target_agents=target_agents,
        enabled_agents=enabled_agents,
    )

    mode = dispatch_mode.strip().lower()
    if mode not in {"direct", "parallel", "router"}:
        mode = "parallel" if len(requested_agents) > 1 else "direct"

    user_forced_agents = bool(target_agents) or bool(initial_agent)
    dispatch_plan = runtime.task_planner.plan(
        message=prompt,
        requested_agents=requested_agents,
        enabled_agents=enabled_agents,
        requested_model=requested_model,
        user_forced_agents=user_forced_agents,
    )
    run_requests = list(dispatch_plan.routes)
    target_list = dispatch_plan.target_agents or requested_agents

    if mode == "direct" and len(run_requests) > 1:
        run_requests = run_requests[:1]
        target_list = [run_requests[0].agent]
    elif mode == "router":
        mode = "parallel" if len(run_requests) > 1 else "direct"

    if not run_requests:
        raise DispatchValidationError(f"No routes resolved for {webhook_type}")

    session_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    dispatch_id = str(uuid.uuid4())

    runtime.session_mgr.start(
        session_id,
        user=session_owner,
        started_at=datetime.now(UTC),
    )

    runtime.session_mgr.add_message(
        session_id=session_id,
        role="user",
        content=prompt,
        agent=run_requests[0].agent if len(run_requests) == 1 else "general",
        model=requested_model,
    )

    runtime.session_mgr.create_dispatch(
        dispatch_id,
        session_id=session_id,
        turn_id=turn_id,
        user=session_owner,
        prompt=prompt,
        dispatch_mode=mode,
        target_agents=target_list,
        status="running",
    )

    runtime.session_mgr.add_event(
        session_id=session_id,
        turn_id=turn_id,
        event_type="dispatch_start",
        payload={
            "type": "dispatch_start",
            "dispatch_id": dispatch_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "dispatch_mode": mode,
            "target_agents": target_list,
            "source": source,
            "webhook_type": webhook_type,
        },
    )

    runtime.session_mgr.add_event(
        session_id=session_id,
        turn_id=turn_id,
        event_type="dispatch_plan",
        payload={
            "type": "dispatch_plan",
            "dispatch_id": dispatch_id,
            "session_id": session_id,
            "turn_id": turn_id,
            **dispatch_plan.to_payload(),
        },
    )

    await runtime.emitter.emit(
        "dispatch_plan_resolved",
        source=source,
        webhook_type=webhook_type,
        dispatch_id=dispatch_id,
        session_id=session_id,
        turn_id=turn_id,
        task_type=dispatch_plan.task_type,
        decomposed=dispatch_plan.decomposed,
        strategy=dispatch_plan.strategy,
        route_count=len(run_requests),
        target_agents=target_list,
    )

    def _persist_run_event(*, run_id: str, event_type: str, payload: dict) -> None:
        runtime.session_mgr.add_run_event(
            run_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            payload=payload,
        )
        runtime.session_mgr.add_event(
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            payload=payload,
        )

    async def _run_route(route: TaskRoute, *, route_index: int) -> dict:
        run_id = str(uuid.uuid4())
        task_id = f"task-{run_id[:8]}"
        route_payload = {
            "task_type": route.task_type,
            "subtask_id": route.subtask_id,
            "skill": route.skill,
            "instruction": route.instruction,
            "route_index": route_index,
        }
        route_prompt = route.prompt
        route_model = route.requested_model or requested_model
        backend_name, active_model = resolve_backend_and_model(
            runtime=runtime,
            agent_name=route.agent,
            requested_model=route_model,
        )
        workspace_cwd = prepare_agent_workspace(session_id=session_id, agent_name=route.agent)
        active_model_id = ui_model_id(backend_name, active_model)
        context_limit = runtime.model_router.get_context_limit(active_model)
        total_cost = 0.0
        tokens_used = 0
        response_parts: list[str] = []

        runtime.session_mgr.start_agent_run(
            run_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            turn_id=turn_id,
            agent=route.agent,
            backend=backend_name,
            model=active_model_id,
            task_type=route.task_type,
            subtask_id=route.subtask_id,
            skill=route.skill,
            status="queued",
        )

        _persist_run_event(
            run_id=run_id,
            event_type="run_start",
            payload={
                "type": "run_start",
                "dispatch_id": dispatch_id,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "agent": route.agent,
                "backend": backend_name,
                "model": active_model_id,
                "workspace_cwd": str(workspace_cwd),
                **route_payload,
            },
        )

        asyncio.get_running_loop().create_task(
            runtime.emitter.emit(
                "routing_decision",
                source=source,
                webhook_type=webhook_type,
                dispatch_id=dispatch_id,
                run_id=run_id,
                agent=route.agent,
                backend=backend_name,
                query_preview=route_prompt[:200],
                task_type=route.task_type,
                subtask_id=route.subtask_id,
                skill=route.skill,
            )
        )

        async def _capture_hook_event(payload: dict) -> None:
            event = {
                **payload,
                "dispatch_id": dispatch_id,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "agent": route.agent,
                **route_payload,
            }
            event_type = str(event.get("type", "tool_result"))
            runtime.session_mgr.add_event(
                session_id=session_id,
                turn_id=turn_id,
                event_type=event_type,
                payload=event,
            )
            runtime.session_mgr.add_run_event(
                run_id,
                dispatch_id=dispatch_id,
                session_id=session_id,
                turn_id=turn_id,
                event_type=event_type,
                payload=event,
            )

        client_options = build_backend_options(
            runtime=runtime,
            user=session_owner,
            websocket=None,
            backend_name=backend_name,
            active_model=active_model,
            agent_name=route.agent,
            ws_callback=_capture_hook_event,
            workspace_cwd=workspace_cwd,
            session_id=session_id,
        )

        _persist_run_event(
            run_id=run_id,
            event_type="run_phase",
            payload={
                "type": "run_phase",
                "dispatch_id": dispatch_id,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "agent": route.agent,
                "phase": "executing",
                "summary": "Agent execution started",
                **route_payload,
            },
        )

        try:
            managed = await runtime.sdk_client_manager.get_or_create(
                session_id, route.agent, lambda: client_options,
            )
            managed.immediate_teardown = True
            managed.active_run = True

            await managed.client.set_model(active_model)

            run_context = RunContext(
                dispatch_id=dispatch_id, run_id=run_id, task_id=task_id,
                session_id=session_id, turn_id=turn_id, agent_name=route.agent,
                model_id=active_model_id, route_payload=route_payload,
            )
            processor = StreamProcessor(
                emitter=None,  # background dispatch persists events directly
                managed_client=managed,
                context_limit=context_limit,
            )

            await runtime.sdk_client_manager.query(session_id, route.agent, route_prompt)
            result = await processor.process_response(run_context)
            runtime.sdk_client_manager.release(session_id, route.agent)

            # Store SDK session ID for future resume
            if result.sdk_session_id:
                runtime.session_mgr.store_sdk_session_id(
                    session_id, route.agent, result.sdk_session_id,
                )

            tokens_used = result.tokens_used
            total_cost = result.cost_usd
            response_parts = [result.response_text] if result.response_text else []

            assistant_text = " ".join(response_parts).strip()
            if assistant_text:
                runtime.session_mgr.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_text,
                    agent=route.agent,
                    model=active_model_id,
                )

            context_pct = round((tokens_used / context_limit) * 100, 1) if context_limit > 0 else 0.0
            runtime.session_mgr.update_agent_run(
                run_id,
                status="done",
                summary=(assistant_text[:160] if assistant_text else "Completed"),
                cost_usd=total_cost,
                tokens_used=tokens_used,
                context_limit=context_limit,
                context_pct=context_pct,
                completed_at=datetime.now(UTC),
            )
            _persist_run_event(
                run_id=run_id,
                event_type="run_complete",
                payload={
                    "type": "run_complete",
                    "dispatch_id": dispatch_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "agent": route.agent,
                    "result": "success",
                    "summary": (assistant_text[:160] if assistant_text else "Completed"),
                    "cost_usd": total_cost,
                    "tokens_used": tokens_used,
                    "context_limit": context_limit,
                    "context_pct": context_pct,
                    **route_payload,
                },
            )
            return {"result": "success", "cost_usd": total_cost, "tokens_used": tokens_used}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe_message = type(exc).__name__
            runtime.session_mgr.update_agent_run(
                run_id,
                status="error",
                summary="Internal error during task execution",
                error=safe_message,
                completed_at=datetime.now(UTC),
            )
            _persist_run_event(
                run_id=run_id,
                event_type="run_complete",
                payload={
                    "type": "run_complete",
                    "dispatch_id": dispatch_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "agent": route.agent,
                    "result": "error",
                    "summary": "Internal error during task execution.",
                    "cost_usd": 0.0,
                    "tokens_used": 0,
                    "context_limit": context_limit,
                    "context_pct": 0.0,
                    **route_payload,
                },
            )
            return {"result": "error", "cost_usd": 0.0, "tokens_used": 0}

    try:
        run_results = await execute_dispatch_runs(
            dispatch_mode=mode,
            run_requests=run_requests,
            max_parallel_agent_runs=max_parallel_agent_runs,
            execute_run=_run_route,
            logger=logger,
        )

        summary = summarize_dispatch_runs(run_results)
        success_count = summary.success_count
        error_count = summary.error_count
        tokens_used = summary.tokens_used
        total_cost = summary.cost_usd
        dispatch_status = summary.status

        runtime.session_mgr.update_dispatch(
            dispatch_id,
            status=dispatch_status,
            error=summary.error,
            completed_at=datetime.now(UTC),
        )

        runtime.session_mgr.add_event(
            session_id=session_id,
            turn_id=turn_id,
            event_type="dispatch_complete",
            payload={
                "type": "dispatch_complete",
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "status": dispatch_status,
                "task_type": dispatch_plan.task_type,
                "decomposed": dispatch_plan.decomposed,
                "strategy": dispatch_plan.strategy,
                "target_agents": target_list,
                "total_runs": summary.total_runs,
                "success_count": success_count,
                "error_count": error_count,
                "interrupted_count": summary.interrupted_count,
                "cost_usd": total_cost,
                "max_parallel": max_parallel_agent_runs,
                "source": source,
                "webhook_type": webhook_type,
            },
        )

        runtime.session_mgr.end(
            session_id=session_id,
            ended_at=datetime.now(UTC),
            message_count=max(1, len(run_results) + 1),
            agents_used=[route.agent for route in run_requests],
        )

        try:
            cleanup_session_workspaces(session_id=session_id)
        except Exception:
            logger.warning("workspace_cleanup_failed", session_id=session_id)

        await runtime.emitter.emit(
            "dispatch_completed",
            source=source,
            webhook_type=webhook_type,
            dispatch_id=dispatch_id,
            session_id=session_id,
            turn_id=turn_id,
            status=dispatch_status,
            task_type=dispatch_plan.task_type,
            decomposed=dispatch_plan.decomposed,
            strategy=dispatch_plan.strategy,
            total_runs=summary.total_runs,
            success_count=success_count,
            error_count=error_count,
            interrupted_count=summary.interrupted_count,
            cost_usd=total_cost,
            tokens_used=tokens_used,
        )

        logger.info(
            "background_dispatch_completed",
            source=source,
            webhook_type=webhook_type,
            routes=len(run_requests),
            status=dispatch_status,
        )

        return DispatchExecutionSummary(
            status=dispatch_status,
            run_count=summary.total_runs,
            success_count=success_count,
            error_count=error_count,
            interrupted_count=summary.interrupted_count,
            tokens_used=tokens_used,
            cost_usd=total_cost,
        )
    except asyncio.CancelledError:
        logger.warning("background_dispatch_cancelled", source=source, webhook_type=webhook_type)
        raise
