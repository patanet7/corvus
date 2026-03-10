"""Claude Agent SDK option builders and model/backend resolution helpers."""

from __future__ import annotations

import logging
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext
from fastapi import WebSocket

from corvus.config import (
    CLAUDE_CONFIG_TEMPLATE,
    CLAUDE_HOME_SCOPE,
    CLAUDE_RUNTIME_HOME,
    ISOLATE_CLAUDE_HOME,
)
from corvus.gateway.confirm_queue import ConfirmQueue
from corvus.gateway.runtime import GatewayRuntime
from corvus.hooks import create_hooks
from corvus.permissions import evaluate_tool_permission, expand_confirm_gated_tools, normalize_permission_mode

logger = logging.getLogger("corvus-gateway")


_CLAUDE_HOME_SCOPE_ALIASES = {
    "deployment": "deployment",
    "shared": "deployment",
    "per_agent": "per_agent",
    "agent": "per_agent",
    "per-agent": "per_agent",
    "per_session_agent": "per_session_agent",
    "session_agent": "per_session_agent",
    "session-agent": "per_session_agent",
    "per-session-agent": "per_session_agent",
}


def _sanitize_fragment(value: str | None, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    token = token.strip("-.")
    return token or fallback


def _normalize_claude_home_scope(scope: str) -> str:
    normalized = _CLAUDE_HOME_SCOPE_ALIASES.get(scope.strip().lower())
    if normalized:
        return normalized
    logger.warning("Unknown CLAUDE home scope '%s'; falling back to deployment", scope)
    return "deployment"


def resolve_claude_runtime_home(
    *,
    base_home: str | Path = CLAUDE_RUNTIME_HOME,
    scope: str = CLAUDE_HOME_SCOPE,
    user: str | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
) -> Path:
    """Resolve scoped Claude runtime home path."""
    root = Path(base_home).expanduser().resolve()
    safe_user = _sanitize_fragment(user, fallback="default-user")
    safe_agent = _sanitize_fragment(agent_name, fallback="default-agent")
    safe_session = _sanitize_fragment(session_id, fallback="default-session")
    mode = _normalize_claude_home_scope(scope)
    if mode == "per_session_agent":
        return root / "users" / safe_user / "sessions" / safe_session / safe_agent
    if mode == "per_agent":
        return root / "users" / safe_user / "agents" / safe_agent
    return root / "users" / safe_user / "shared"


# Environment variables passed through to the SDK subprocess.
# Security: allowlist only — never blocklist. Only safe, non-secret system vars
# plus LLM provider keys that the subprocess needs to authenticate.
_SDK_ENV_PASSTHROUGH: frozenset[str] = frozenset({
    # System essentials
    "PATH", "SHELL", "TERM", "LANG", "LC_ALL",
    "TMPDIR", "USER", "LOGNAME",
    # LLM provider credentials (injected by SOPS credential store)
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OLLAMA_BASE_URL",
    "KIMI_BOT_TOKEN",
    "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY",
    "CODEX_API_KEY",
})


def apply_claude_runtime_env(
    opts: ClaudeAgentOptions,
    *,
    isolate: bool = ISOLATE_CLAUDE_HOME,
    runtime_home: str | Path = CLAUDE_RUNTIME_HOME,
    config_template: str | Path = CLAUDE_CONFIG_TEMPLATE,
) -> None:
    """Scope Claude CLI state under deployment-local runtime home.

    Seeds opts.env with the allowlisted parent-process env vars so the SDK
    subprocess can find PATH, LLM credentials, etc. Then overrides HOME and
    XDG paths to the isolated runtime directory.
    """
    # Seed allowlisted env vars from the parent process so the SDK subprocess
    # inherits PATH, ANTHROPIC_API_KEY, etc.
    for key in _SDK_ENV_PASSTHROUGH:
        val = os.environ.get(key)
        if val is not None:
            opts.env[key] = val

    if not isolate:
        return

    home = Path(runtime_home).expanduser().resolve()
    claude_config = home / ".claude"
    xdg_config = home / ".config"
    xdg_cache = home / ".cache"
    xdg_state = home / ".local" / "state"
    xdg_data = home / ".local" / "share"
    for path in (home, claude_config, xdg_config, xdg_cache, xdg_state, xdg_data):
        path.mkdir(parents=True, exist_ok=True)
    config_json = claude_config / ".claude.json"
    if not config_json.exists():
        template = Path(config_template).expanduser().resolve()
        if template.is_file():
            shutil.copyfile(template, config_json)
        else:
            # Seed minimal config to avoid first-run CLI warnings about missing config.
            config_json.write_text("{}\n", encoding="utf-8")

    # Override HOME and XDG paths so SDK subprocess writes to isolated runtime dir.
    opts.env["HOME"] = str(home)
    opts.env["CLAUDE_CONFIG_DIR"] = str(claude_config)
    opts.env["XDG_CONFIG_HOME"] = str(xdg_config)
    opts.env["XDG_CACHE_HOME"] = str(xdg_cache)
    opts.env["XDG_STATE_HOME"] = str(xdg_state)
    opts.env["XDG_DATA_HOME"] = str(xdg_data)


def apply_workspace_context(opts: ClaudeAgentOptions, *, workspace_cwd: str | Path | None) -> None:
    """Apply isolated workspace cwd/add-dir context to SDK options."""
    if workspace_cwd is None:
        return
    cwd = Path(workspace_cwd).expanduser().resolve()
    opts.cwd = cwd

    existing = {str(Path(item).expanduser().resolve()) for item in opts.add_dirs}
    if str(cwd) not in existing:
        opts.add_dirs = [cwd, *opts.add_dirs]


def build_hooks(
    runtime: GatewayRuntime,
    websocket: WebSocket | None = None,
    ws_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    confirm_gated: set[str] | None = None,
    allow_secret_access: bool = False,
) -> dict[str, list[HookMatcher]]:
    """Build hook config using EventEmitter-backed hooks."""

    async def ws_forward(msg: dict[str, Any]) -> None:
        if ws_callback:
            await ws_callback(msg)
            return
        if websocket:
            try:
                await websocket.send_json(msg)
            except Exception:
                logger.warning(
                    "ws_forward: connection closed, cannot send %s",
                    msg.get("type", "unknown"),
                )

    event_hooks = create_hooks(
        runtime.emitter,
        ws_callback=ws_forward if (websocket or ws_callback) else None,
        confirm_gated=confirm_gated,
        allow_secret_access=allow_secret_access,
    )
    return {
        "PreToolUse": [
            HookMatcher(matcher="Bash|Read|mcp__.*", hooks=[event_hooks["pre_tool_use"]]),
        ],
        "PostToolUse": [
            HookMatcher(matcher=".*", hooks=[event_hooks["post_tool_use"]]),
        ],
    }


def build_options(
    runtime: GatewayRuntime,
    user: str,
    websocket: WebSocket | None = None,
    ws_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    allow_secret_access: bool = False,
    agent_name: str | None = None,
    confirm_queue: ConfirmQueue | None = None,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions from hub-managed agent/runtime configuration."""
    del user  # Reserved for future per-user policy overlay.

    build_result = runtime.agents_hub.build_all()
    if build_result.errors:
        logger.error(
            "Hub build completed with errors: %s; running in degraded mode",
            build_result.errors,
        )

    agents = build_result.agents
    selected_agents = agents
    if agent_name:
        selected = agents.get(agent_name)
        if selected is not None:
            selected_agents = {agent_name: selected}
        else:
            logger.warning("Requested agent '%s' missing from build result; using full agent set", agent_name)

    if agent_name:
        spec = runtime.agents_hub.get_agent(agent_name)
        gated = (
            expand_confirm_gated_tools(agent_name, spec.tools.confirm_gated)
            if spec is not None
            else runtime.agents_hub.get_confirm_gated_tools()
        )
    else:
        gated = runtime.agents_hub.get_confirm_gated_tools()

    # Collect MCP servers from all enabled agents (capability tools + memory)
    mcp_servers: dict[str, Any] = {}
    for name in selected_agents:
        agent_servers = runtime.agents_hub.build_mcp_servers(name)
        mcp_servers.update(agent_servers)

    permission_mode = _resolve_permission_mode(
        runtime=runtime,
        agent_name=agent_name,
        allow_secret_access=allow_secret_access,
    )
    can_use_tool = _build_can_use_tool(
        runtime=runtime,
        agent_name=agent_name,
        allow_secret_access=allow_secret_access,
        ws_callback=ws_callback,
        confirm_queue=confirm_queue,
    )

    opts_kwargs: dict[str, Any] = {
        "system_prompt": runtime.agents_hub.build_system_prompt(agent_name or "huginn"),
        "setting_sources": ["project"],
        "agents": selected_agents,
        "hooks": build_hooks(
            runtime=runtime,
            websocket=websocket,
            ws_callback=ws_callback,
            confirm_gated=gated,
            allow_secret_access=allow_secret_access,
        ),
        "permission_mode": permission_mode,
    }
    if can_use_tool is not None:
        opts_kwargs["can_use_tool"] = can_use_tool
    if mcp_servers:
        opts_kwargs["mcp_servers"] = mcp_servers

    return ClaudeAgentOptions(**opts_kwargs)


def _resolve_permission_mode(
    *,
    runtime: GatewayRuntime,
    agent_name: str | None,
    allow_secret_access: bool,
) -> str:
    """Resolve SDK permission mode from break-glass + per-agent metadata."""
    if allow_secret_access:
        return "bypassPermissions"
    if not agent_name:
        return "default"
    spec = runtime.agents_hub.get_agent(agent_name)
    metadata_mode: str | None = None
    if spec and isinstance(spec.metadata, dict):
        raw = spec.metadata.get("permission_mode")
        metadata_mode = str(raw).strip() if isinstance(raw, str) and raw.strip() else None
    return normalize_permission_mode(metadata_mode, fallback="default")


def _build_can_use_tool(
    *,
    runtime: GatewayRuntime,
    agent_name: str | None,
    allow_secret_access: bool,
    ws_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    confirm_queue: ConfirmQueue | None = None,
) -> Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResultAllow | PermissionResultDeny],
] | None:
    """Build SDK-native dynamic tool permission callback."""
    if not agent_name:
        return None
    spec = runtime.agents_hub.get_agent(agent_name)
    if spec is None:
        return None

    async def _can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        del context
        decision = evaluate_tool_permission(
            agent_name=agent_name,
            spec=spec,
            capabilities=runtime.capabilities_registry,
            tool_name=tool_name,
            allow_secret_access=allow_secret_access,
        )
        await runtime.emitter.emit(
            "tool_permission_decision",
            agent=agent_name,
            tool=tool_name,
            allowed=decision.allowed,
            state=decision.state,
            scope=decision.scope,
            reason=decision.reason,
        )
        if ws_callback is not None:
            await ws_callback(
                {
                    "type": "tool_permission_decision",
                    "agent": agent_name,
                    "tool": tool_name,
                    "allowed": decision.allowed,
                    "state": decision.state,
                    "scope": decision.scope,
                    "reason": decision.reason,
                }
            )
        if decision.allowed and decision.state == "confirm":
            # Gated tool — send confirm request via WS, then block
            call_id = tool_name  # Use tool_name as call_id for correlation
            if ws_callback is not None:
                await ws_callback(
                    {
                        "type": "confirm_request",
                        "tool": tool_name,
                        "params": tool_input,
                        "call_id": call_id,
                        "timeout_s": 60,
                    }
                )
            if confirm_queue is not None:
                approved = await confirm_queue.wait_for_confirmation(call_id)
                if approved:
                    return PermissionResultAllow()
                return PermissionResultDeny(
                    message=f"User denied tool '{tool_name}'.",
                    interrupt=False,
                )
            # No confirm queue — deny by default. Break-glass handled earlier.
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' requires confirmation but no confirm queue is available.",
                interrupt=False,
            )
        if decision.allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message=decision.reason, interrupt=False)

    return _can_use_tool


def any_llm_configured() -> bool:
    """Check whether at least one LLM backend credential is configured."""
    return any(
        os.environ.get(var)
        for var in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OLLAMA_BASE_URL",
            "KIMI_BOT_TOKEN",
            "OPENAI_COMPAT_BASE_URL",
        )
    )


def resolve_backend_and_model(
    runtime: GatewayRuntime,
    agent_name: str,
    requested_model: str | None,
) -> tuple[str, str]:
    """Resolve backend/model pair for the next SDK query.

    With LiteLLM proxy handling routing, this just returns the configured
    model name. LiteLLM handles fallbacks, retries, and backend selection.
    """
    if requested_model:
        token = requested_model.strip()
        if "/" in token:
            prefix, _, model_name = token.partition("/")
            if model_name:
                return prefix, model_name
        return "litellm", token

    configured = runtime.model_router.get_model(agent_name).strip()
    backend = runtime.model_router.get_backend(agent_name)
    return backend, configured


def ui_default_model(runtime: GatewayRuntime) -> str:
    """Return configured default model id for frontend selection logic."""
    return runtime.model_router.default_model


def ui_model_id(backend_name: str, active_model: str) -> str:
    """Return model id shape expected by frontend selectors."""
    if backend_name == "claude":
        return active_model
    return f"{backend_name}/{active_model}"


def build_backend_options(
    runtime: GatewayRuntime,
    user: str,
    websocket: WebSocket | None,
    backend_name: str,
    active_model: str,
    agent_name: str | None = None,
    ws_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    allow_secret_access: bool = False,
    workspace_cwd: str | Path | None = None,
    session_id: str | None = None,
    confirm_queue: ConfirmQueue | None = None,
) -> ClaudeAgentOptions:
    """Build backend-specific ClaudeAgentOptions for persistent SDK clients."""
    opts = build_options(
        runtime=runtime,
        user=user,
        websocket=websocket,
        ws_callback=ws_callback,
        allow_secret_access=allow_secret_access,
        agent_name=agent_name,
        confirm_queue=confirm_queue,
    )
    apply_claude_runtime_env(
        opts,
        runtime_home=resolve_claude_runtime_home(
            user=user,
            agent_name=agent_name,
            session_id=session_id,
        ),
    )
    apply_workspace_context(opts, workspace_cwd=workspace_cwd)

    # Backends that support tool calling (via LiteLLM translation) keep
    # tools enabled.  Chat-only backends get tools stripped.
    _TOOL_CAPABLE_BACKENDS = {"claude", "ollama"}
    if backend_name not in _TOOL_CAPABLE_BACKENDS:
        opts.tools = []
        opts.allowed_tools = []
        opts.disallowed_tools = []
        opts.mcp_servers = {}
        opts.hooks = None
        opts.agents = None
        opts.can_use_tool = None
        opts.model = active_model

    return opts
