"""Permission evaluation helpers shared across runtime and API surfaces.

This module centralizes tool permission decisions so SDK runtime gating and
frontend policy inspection stay consistent and DRY.
"""

from __future__ import annotations

from dataclasses import dataclass

from corvus.agents.spec import AgentSpec
from corvus.capabilities.registry import CapabilitiesRegistry

_UNHEALTHY_STATUSES = {"error", "offline", "unhealthy"}
_VALID_PERMISSION_MODES = {"default", "acceptEdits", "plan", "bypassPermissions"}


@dataclass(frozen=True, slots=True)
class ToolPermissionDecision:
    """Structured decision for a single tool invocation."""

    allowed: bool
    state: str  # allow | deny | confirm
    scope: str
    subject: str
    reason: str


def normalize_permission_mode(value: str | None, *, fallback: str = "default") -> str:
    """Return an SDK-valid permission mode."""
    if value and value in _VALID_PERMISSION_MODES:
        return value
    return fallback


def expand_confirm_gated_tools(agent_name: str, confirm_gated: list[str]) -> set[str]:
    """Expand short confirm-gated tool names into SDK MCP tool identifiers."""
    expanded: set[str] = set()
    for name in confirm_gated:
        token = str(name).strip()
        if not token:
            continue
        expanded.add(token)
        if "." not in token:
            continue
        module_name, action = token.split(".", 1)
        expanded.add(f"mcp__{module_name}_{agent_name}__{module_name}_{action}")
        expanded.add(f"mcp__{module_name}__{module_name}_{action}")
    return expanded


def _parse_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    """Parse MCP tool name shape: ``mcp__{server}__{tool}``."""
    if not tool_name.startswith("mcp__"):
        return None
    _, _, remainder = tool_name.partition("mcp__")
    server, sep, tool = remainder.partition("__")
    if not sep or not server or not tool:
        return None
    return server, tool


def evaluate_tool_permission(
    *,
    agent_name: str,
    spec: AgentSpec,
    capabilities: CapabilitiesRegistry,
    tool_name: str,
    allow_secret_access: bool = False,
) -> ToolPermissionDecision:
    """Evaluate whether a tool call is allowed for an agent."""
    confirm_gated = expand_confirm_gated_tools(agent_name, spec.tools.confirm_gated)
    confirm_state = tool_name in confirm_gated

    if allow_secret_access:
        return ToolPermissionDecision(
            allowed=True,
            state="allow",
            scope="break_glass",
            subject=tool_name,
            reason="Break-glass session active: runtime policy bypass enabled.",
        )

    parsed = _parse_mcp_tool_name(tool_name)
    if parsed is None:
        if tool_name in spec.tools.builtin:
            return ToolPermissionDecision(
                allowed=True,
                state="confirm" if confirm_state else "allow",
                scope="builtin_tool",
                subject=tool_name,
                reason=(
                    "Builtin tool is configured and requires explicit confirmation."
                    if confirm_state
                    else "Builtin tool is configured for this agent."
                ),
            )
        return ToolPermissionDecision(
            allowed=False,
            state="deny",
            scope="builtin_tool",
            subject=tool_name,
            reason=f"Builtin tool '{tool_name}' is not allowed for agent '{agent_name}'.",
        )

    server_name, _tool_suffix = parsed
    if server_name.startswith("memory_"):
        expected = f"memory_{agent_name}"
        if server_name != expected:
            return ToolPermissionDecision(
                allowed=False,
                state="deny",
                scope="memory_access",
                subject=tool_name,
                reason=(
                    f"Memory tool server '{server_name}' does not match agent scope '{expected}'. "
                    "Cross-agent memory access is blocked."
                ),
            )
        return ToolPermissionDecision(
            allowed=True,
            state="confirm" if confirm_state else "allow",
            scope="memory_access",
            subject=tool_name,
            reason=(
                "Agent-scoped memory tool requires explicit confirmation."
                if confirm_state
                else "Agent-scoped memory tool is allowed."
            ),
        )

    suffix = f"_{agent_name}"
    module_name = server_name[: -len(suffix)] if server_name.endswith(suffix) else server_name
    if module_name not in spec.tools.modules:
        return ToolPermissionDecision(
            allowed=False,
            state="deny",
            scope="module_access",
            subject=tool_name,
            reason=(
                f"Capability module '{module_name}' is not configured for agent '{agent_name}'."
            ),
        )
    if not capabilities.is_allowed(agent_name, module_name):
        return ToolPermissionDecision(
            allowed=False,
            state="deny",
            scope="module_access",
            subject=tool_name,
            reason=(
                f"Capability module '{module_name}' is unavailable (missing env or unregistered)."
            ),
        )
    health = capabilities.health(module_name)
    if health.status in _UNHEALTHY_STATUSES:
        detail = f" ({health.detail})" if health.detail else ""
        return ToolPermissionDecision(
            allowed=False,
            state="deny",
            scope="module_access",
            subject=tool_name,
            reason=f"Capability module '{module_name}' is unhealthy: {health.status}{detail}",
        )
    return ToolPermissionDecision(
        allowed=True,
        state="confirm" if confirm_state else "allow",
        scope="module_access",
        subject=tool_name,
        reason=(
            f"Capability module '{module_name}' is allowed and requires explicit confirmation."
            if confirm_state
            else f"Capability module '{module_name}' is allowed for this agent."
        ),
    )


def build_policy_entries(
    *,
    agent_name: str,
    spec: AgentSpec,
    capabilities: CapabilitiesRegistry,
    allow_secret_access: bool = False,
) -> list[dict[str, str]]:
    """Build frontend-ready policy entries from current runtime state."""
    entries: list[dict[str, str]] = []
    confirm_gated = expand_confirm_gated_tools(agent_name, spec.tools.confirm_gated)

    for tool_name in sorted(spec.tools.builtin):
        state = "confirm" if tool_name in confirm_gated else "allow"
        reason = (
            "Builtin tool is configured and requires explicit confirmation."
            if state == "confirm"
            else "Builtin tool is configured for this agent."
        )
        entries.append(
            {
                "key": f"builtin:{tool_name}",
                "scope": "builtin_tool",
                "subject": tool_name,
                "state": state,
                "reason": reason,
            }
        )

    for module_name in sorted(spec.tools.modules.keys()):
        if allow_secret_access:
            state = "allow"
            reason = "Break-glass session active: capability policy bypass enabled."
        elif not capabilities.is_allowed(agent_name, module_name):
            state = "deny"
            reason = "Capability module unavailable (missing env or unregistered)."
        else:
            health = capabilities.health(module_name)
            if health.status in _UNHEALTHY_STATUSES:
                state = "deny"
                reason = f"Capability module unhealthy: {health.status}"
                if health.detail:
                    reason = f"{reason} ({health.detail})"
            else:
                state = "allow"
                reason = "Capability module allowed by registry policy."

        entries.append(
            {
                "key": f"module:{module_name}",
                "scope": "module_access",
                "subject": module_name,
                "state": state,
                "reason": reason,
            }
        )

    for confirm_name in sorted(spec.tools.confirm_gated):
        entries.append(
            {
                "key": f"confirm:{confirm_name}",
                "scope": "tool_confirmation",
                "subject": confirm_name,
                "state": "confirm",
                "reason": "Tool requires explicit user confirmation before execution.",
            }
        )

    entries.append(
        {
            "key": f"memory:memory_{agent_name}",
            "scope": "memory_access",
            "subject": f"memory_{agent_name}",
            "state": "allow",
            "reason": "Agent-scoped memory server is always attached for this agent.",
        }
    )

    return entries
