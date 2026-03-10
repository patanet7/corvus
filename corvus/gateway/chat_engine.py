"""Chat dispatch resolution engine.

Extracts target-agent + planner resolution from the WebSocket transport loop so
chat transport can stay focused on protocol concerns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from corvus.gateway.runtime import GatewayRuntime
from corvus.gateway.task_planner import DispatchPlan, TaskRoute

logger = logging.getLogger("corvus-gateway.chat-engine")

_VALID_DISPATCH_MODES = {"router", "direct", "parallel"}


@dataclass(slots=True)
class ChatDispatchResolution:
    """Resolved per-turn dispatch execution inputs."""

    target_agents: list[str]
    run_requests: list[TaskRoute]
    dispatch_mode: str
    dispatch_plan: DispatchPlan


@dataclass(slots=True)
class ChatDispatchError:
    """Typed error payload emitted by chat transport."""

    error: str
    message: str


def resolve_default_agent(runtime: GatewayRuntime) -> str:
    """Resolve default dispatch target from enabled agents."""
    enabled_agents = [agent for agent in runtime.agents_hub.list_agents() if agent.enabled]
    if any(agent.name == "general" for agent in enabled_agents):
        return "general"
    if enabled_agents:
        return enabled_agents[0].name
    return "general"


async def resolve_chat_dispatch(
    *,
    runtime: GatewayRuntime,
    user_message: str,
    requested_agent: object,
    requested_agents: object,
    requested_model: str | None,
    dispatch_mode_raw: object,
) -> tuple[ChatDispatchResolution | None, ChatDispatchError | None]:
    """Resolve routing targets + planner routes for a chat turn."""
    enabled_agent_names = [agent.name for agent in runtime.agents_hub.list_agents() if agent.enabled]
    enabled_lookup = {name.lower(): name for name in enabled_agent_names}
    default_agent = resolve_default_agent(runtime)

    target_agents: list[str] = []
    invalid_agent: str | None = None

    if isinstance(requested_agents, list) and requested_agents:
        for raw in requested_agents:
            token = str(raw).strip().lower()
            if not token:
                continue
            if token in {"all", "@all"}:
                target_agents.extend(enabled_agent_names)
                continue
            if token not in enabled_lookup:
                invalid_agent = token
                break
            target_agents.append(enabled_lookup[token])
    elif isinstance(requested_agent, str) and requested_agent.strip():
        token = requested_agent.strip().lower()
        if token in {"all", "@all"}:
            target_agents = list(enabled_agent_names)
        elif token in enabled_lookup:
            target_agents = [enabled_lookup[token]]
        else:
            invalid_agent = token
    else:
        try:
            classified = await runtime.router_agent.classify(user_message)
        except Exception as exc:
            logger.error(
                "Router agent classification failed: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return None, ChatDispatchError(
                error="router_error",
                message=f"Router classification failed ({type(exc).__name__}). "
                f"Check API key configuration and try again.",
            )
        target_agents = [classified if classified in enabled_lookup else default_agent]

    if invalid_agent:
        return None, ChatDispatchError(
            error="invalid_agent",
            message=f"Unknown or disabled agent: {invalid_agent}",
        )

    # Preserve order, remove duplicates.
    deduped_targets: list[str] = []
    seen: set[str] = set()
    for name in target_agents:
        if name in seen:
            continue
        seen.add(name)
        deduped_targets.append(name)
    target_agents = deduped_targets or [default_agent]

    user_forced_agents = bool(
        (isinstance(requested_agents, list) and requested_agents)
        or (isinstance(requested_agent, str) and requested_agent.strip())
    )

    dispatch_plan = runtime.task_planner.plan(
        message=user_message,
        requested_agents=target_agents,
        enabled_agents=enabled_agent_names,
        requested_model=requested_model,
        user_forced_agents=user_forced_agents,
    )

    run_requests = list(dispatch_plan.routes)
    target_agents = dispatch_plan.target_agents or target_agents

    dispatch_mode_input = str(dispatch_mode_raw).strip().lower() if isinstance(dispatch_mode_raw, str) else ""
    if dispatch_mode_input not in _VALID_DISPATCH_MODES:
        dispatch_mode = "parallel" if len(run_requests) > 1 else "direct"
    elif dispatch_mode_input == "router":
        dispatch_mode = "parallel" if len(run_requests) > 1 else "direct"
    else:
        dispatch_mode = dispatch_mode_input

    if dispatch_mode == "direct" and len(run_requests) > 1:
        run_requests = run_requests[:1]
        target_agents = [run_requests[0].agent]

    if not run_requests:
        return None, ChatDispatchError(
            error="no_dispatch_routes",
            message="No eligible dispatch routes were resolved for this request.",
        )

    return (
        ChatDispatchResolution(
            target_agents=target_agents,
            run_requests=run_requests,
            dispatch_mode=dispatch_mode,
            dispatch_plan=dispatch_plan,
        ),
        None,
    )
