"""corvus chat -- launch Claude Code CLI with Corvus agent configuration.

Entry point: ``uv run python -m corvus.cli.chat``
Or via mise: ``mise run chat``

Builds the full GatewayRuntime (memory, model routing, tools, permissions),
resolves agent configuration, then launches the ``claude`` CLI binary in an
isolated environment with the agent's system prompt, model, and permissions.

The model router (LiteLLM proxy) runs on localhost:4000 and the CLI
inherits ANTHROPIC_BASE_URL so all requests route through it.

Environment isolation prevents the claude binary from reading the user's
global ~/.claude/ (plugins, settings, MCP configs). Each agent gets its
own scoped runtime home under .data/claude-home/.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("corvus-cli")

# ---------------------------------------------------------------------------
# Subprocess environment allowlist (F-001)
# ---------------------------------------------------------------------------
# Only these vars are copied from the parent into the Claude CLI subprocess.
# Credentials (ANTHROPIC_API_KEY, HA_TOKEN, PAPERLESS_API_TOKEN, AWS_*,
# etc.) are NEVER forwarded.  Tools receive credentials in-process via
# ToolContext, not via the subprocess environment.
# ---------------------------------------------------------------------------
_ALLOWED_ENV: frozenset[str] = frozenset({
    "PATH", "HOME", "SHELL", "TERM", "LANG", "LC_ALL",
    "TMPDIR", "USER", "LOGNAME",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR", "XDG_STATE_HOME",
})


def _build_subprocess_env(
    *,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal environment for the Claude CLI subprocess.

    Only explicitly allowed vars from the parent process plus any
    *extra* vars (like ANTHROPIC_BASE_URL when LiteLLM is running)
    are included.  Credentials NEVER leak via environment.
    """
    env: dict[str, str] = {}
    for key in _ALLOWED_ENV:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    if extra:
        env.update(extra)
    return env


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for corvus chat."""
    parser = argparse.ArgumentParser(
        prog="corvus chat",
        description="Launch Claude Code CLI with Corvus agent configuration",
    )
    parser.add_argument("--agent", type=str, default=None, help="Agent name to chat with")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override model (e.g. ollama/qwen3:8b)",
    )
    parser.add_argument("--resume", type=str, default=None, help="Resume session by ID")
    parser.add_argument("--budget", type=float, default=None, help="Spend cap in USD")
    parser.add_argument("--max-turns", type=int, default=None, help="Max conversation turns")
    parser.add_argument("--permission", type=str, default=None, help="Permission mode")
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="List available agents and exit",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show the claude command before launching",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_mode",
        help="Pass --print to claude (non-interactive, pipe-friendly)",
    )
    return parser.parse_args(argv)


def _find_claude_binary() -> str:
    """Find the claude CLI binary path."""
    candidates = [
        shutil.which("claude"),
        shutil.which("wezcld"),
        os.path.expanduser("~/.local/share/wezcld/bin/wezcld"),
        os.path.expanduser("~/.claude/local/claude"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    print(
        "Error: claude CLI binary not found. Install Claude Code first.",
        file=sys.stderr,
    )
    sys.exit(1)


def _pick_agent_interactive(runtime: object) -> str:
    """Interactive agent picker when --agent is not specified."""
    from corvus.cli.chat_render import render_welcome

    agents = runtime.agent_registry.list_enabled()  # type: ignore[attr-defined]
    agents = [a for a in agents if a.name != "huginn"]
    welcome_data = [(a.name, a.description.strip()) for a in agents]
    print(render_welcome(welcome_data))

    while True:
        try:
            choice = input("  Agent: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if choice in {a.name for a in agents}:
            return choice
        print(f"  Unknown agent '{choice}'. Try one of: {', '.join(a.name for a in agents)}")


def _handle_list_agents(runtime: object) -> None:
    """Print available agents and return."""
    from corvus.cli.chat_render import render_welcome

    agents = runtime.agent_registry.list_enabled()  # type: ignore[attr-defined]
    agents = [a for a in agents if a.name != "huginn"]
    welcome_data = [(a.name, a.description.strip()) for a in agents]
    print(render_welcome(welcome_data))


def _handle_list_models(runtime: object) -> None:
    """Print available models and return."""
    models = runtime.model_router.list_models()  # type: ignore[attr-defined]
    print(f"\n  Available models ({len(models)}):\n")
    for m in models:
        default_tag = " (default)" if m.is_default else ""
        print(f"    {m.id:30s}  {m.backend:10s}  {m.label}{default_tag}")
    print()


def _prepare_isolated_env(
    agent_name: str,
    runtime: object,
    workspace_cwd: Path | None = None,
) -> dict[str, str]:
    """Build an isolated environment for the claude subprocess.

    Prevents the claude binary from reading the user's global ~/.claude/
    (plugins, settings, MCP configs). Each agent gets its own scoped
    runtime home under .data/claude-home/.
    """
    from corvus.config import CLAUDE_CONFIG_TEMPLATE, CLAUDE_RUNTIME_HOME
    from corvus.gateway.options import resolve_claude_runtime_home

    # Build a minimal env — only allowlisted vars plus ANTHROPIC_BASE_URL
    # which the LiteLLM manager sets in os.environ at startup.
    subprocess_extra: dict[str, str] = {}
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url is not None:
        subprocess_extra["ANTHROPIC_BASE_URL"] = base_url
    env = _build_subprocess_env(extra=subprocess_extra)

    # Resolve per-agent runtime home
    runtime_home = resolve_claude_runtime_home(
        base_home=CLAUDE_RUNTIME_HOME,
        user="cli",
        agent_name=agent_name,
    )

    # Create isolated directory structure
    claude_config = runtime_home / ".claude"
    xdg_config = runtime_home / ".config"
    xdg_cache = runtime_home / ".cache"
    xdg_state = runtime_home / ".local" / "state"
    xdg_data = runtime_home / ".local" / "share"
    for path in (runtime_home, claude_config, xdg_config, xdg_cache, xdg_state, xdg_data):
        path.mkdir(parents=True, exist_ok=True)

    # Seed minimal config if absent
    config_json = claude_config / ".claude.json"
    if not config_json.exists():
        template = Path(CLAUDE_CONFIG_TEMPLATE).expanduser().resolve()
        if template.is_file():
            shutil.copyfile(template, config_json)
        else:
            config_json.write_text("{}\n", encoding="utf-8")

    # Ensure .claude.json has onboarding-complete markers, workspace trust,
    # and API key approval so Claude Code skips all first-run prompts.
    try:
        existing = json.loads(config_json.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        existing = {}

    onboarding_defaults = {
        "hasCompletedOnboarding": True,
        "hasAcknowledgedDisclaimer": True,
    }
    updated = False
    for key, val in onboarding_defaults.items():
        if key not in existing:
            existing[key] = val
            updated = True

    # Pre-approve the ANTHROPIC_API_KEY so Claude Code doesn't prompt.
    # Read from os.environ (NOT the subprocess env — the key is
    # intentionally excluded from the subprocess for security).
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        key_suffix = api_key[-20:]
        responses = existing.setdefault("customApiKeyResponses", {"approved": [], "rejected": []})
        if key_suffix not in responses.get("approved", []):
            responses.setdefault("approved", []).append(key_suffix)
            updated = True

    # Pre-trust the workspace directory so the trust dialog is skipped.
    workspace_path = str(workspace_cwd) if workspace_cwd else str(Path.cwd())
    projects = existing.setdefault("projects", {})
    if workspace_path not in projects:
        projects[workspace_path] = {}
    project_entry = projects[workspace_path]
    trust_defaults = {
        "hasTrustDialogAccepted": True,
        "hasCompletedProjectOnboarding": True,
    }
    for key, val in trust_defaults.items():
        if not project_entry.get(key):
            project_entry[key] = val
            updated = True

    if updated:
        config_json.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    # Seed settings.json with sensible defaults for agent sessions.
    settings_json = claude_config / "settings.json"
    if not settings_json.exists():
        settings_json.write_text("{}\n", encoding="utf-8")

    # Copy agent-specific skills into the isolated home
    from corvus.gateway.workspace_runtime import copy_agent_skills

    config_dir = Path(__file__).resolve().parent.parent.parent
    spec = runtime.agents_hub.get_agent(agent_name)  # type: ignore[attr-defined]
    shared_skills = None
    if spec and isinstance(spec.metadata, dict):
        shared_skills = spec.metadata.get("shared_skills")
    copy_agent_skills(
        agent_name=agent_name,
        config_dir=config_dir,
        workspace_dir=runtime_home,
        shared_skills=shared_skills,
    )

    # Override env to isolate claude from user-global state.
    # CLAUDE_CONFIG_DIR must be isolated to prevent global plugins/MCP/settings
    # from leaking in. Auth works via ANTHROPIC_API_KEY (injected by
    # init_credentials from SOPS store) routed through the LiteLLM proxy.
    env["HOME"] = str(runtime_home)
    env["CLAUDE_CONFIG_DIR"] = str(claude_config)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["XDG_STATE_HOME"] = str(xdg_state)
    env["XDG_DATA_HOME"] = str(xdg_data)

    return env


def _build_agent_mcp_config(
    agent_name: str,
    runtime: object,
    isolated_home: Path,
) -> Path | None:
    """Generate MCP config for the agent's allowed tools.

    Reads the agent's tool modules from its spec, resolves required env vars
    from the capabilities registry, and merges any external MCP servers
    declared in the agent YAML.

    Returns the config file path, or None if the agent is not found or
    generation fails.
    """
    from corvus.cli.mcp_config import build_mcp_config

    spec = runtime.agents_hub.get_agent(agent_name)  # type: ignore[attr-defined]
    if spec is None:
        return None

    # Determine which modules this agent requests
    module_configs: dict[str, dict] = {}
    requires_env_by_module: dict[str, list[str]] = {}
    if hasattr(spec.tools, "modules") and spec.tools.modules:
        module_configs = dict(spec.tools.modules)

    # Build requires_env mapping from the capabilities registry
    caps = runtime.capabilities_registry  # type: ignore[attr-defined]
    for module_name in module_configs:
        entry = caps.get_module(module_name)
        if entry is not None:
            requires_env_by_module[module_name] = list(entry.requires_env)

    # External MCP servers from agent spec
    external_servers = getattr(spec.tools, "mcp_servers", []) or []

    # Memory domain
    memory_domain = spec.memory.own_domain if spec.memory else "shared"

    try:
        return build_mcp_config(
            agent_name=agent_name,
            module_configs=module_configs,
            requires_env_by_module=requires_env_by_module,
            external_mcp_servers=external_servers,
            output_dir=isolated_home,
            memory_domain=memory_domain,
        )
    except Exception as exc:
        logger.warning("MCP config generation failed: %s — tools unavailable in CLI", exc)
        return None


def _seed_agent_settings(
    isolated_home: Path,
    model_id: str,
) -> None:
    """Seed settings.json with agent-appropriate defaults.

    Locks the model to the agent's configured value and disables
    features that don't make sense in an agent session.
    """
    settings_path = isolated_home / ".claude" / "settings.json"
    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        existing = {}

    desired = {
        "model": model_id,
        "availableModels": [model_id],
        "verbose": True,
        "includeCoAuthoredBy": False,
        "autoUpdates": False,
    }
    updated = False
    for key, val in desired.items():
        if existing.get(key) != val:
            existing[key] = val
            updated = True
    if updated:
        settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def _build_claude_cmd(
    claude_bin: str,
    runtime: object,
    agent_name: str,
    args: argparse.Namespace,
    mcp_config_path: Path | None = None,
) -> list[str]:
    """Build the full claude CLI command from agent configuration."""
    from corvus.gateway.options import resolve_backend_and_model
    from corvus.permissions import normalize_permission_mode

    cmd: list[str] = [claude_bin]

    # --- Isolation flags ---
    # Only use MCP servers we explicitly pass, ignore global configs
    cmd.append("--strict-mcp-config")
    # Load user + project settings from the isolated HOME (blocks real
    # user-level plugins/skills since HOME is overridden).
    cmd.extend(["--setting-sources", "user,project"])

    # System prompt — full 6-layer composition (soul, agent soul, identity,
    # prompt, siblings, memory context)
    system_prompt = runtime.agents_hub.build_system_prompt(agent_name)  # type: ignore[attr-defined]
    cmd.extend(["--system-prompt", system_prompt])

    # Model — resolved through model router (LiteLLM proxy handles routing)
    backend, model = resolve_backend_and_model(runtime, agent_name, args.model)  # type: ignore[arg-type]
    model_id = model if backend == "claude" else f"{backend}/{model}"
    cmd.extend(["--model", model_id])

    # Permission mode
    spec = runtime.agents_hub.get_agent(agent_name)  # type: ignore[attr-defined]
    if args.permission:
        permission_mode = args.permission
    elif spec and isinstance(spec.metadata, dict):
        raw = spec.metadata.get("permission_mode")
        permission_mode = normalize_permission_mode(
            str(raw).strip() if isinstance(raw, str) and raw.strip() else None,
            fallback="default",
        )
    else:
        permission_mode = "default"
    cmd.extend(["--permission-mode", permission_mode])

    # Allowed tools from agent spec (auto-approve these)
    allowed: list[str] = []
    if spec and spec.tools.builtin:
        allowed.extend(spec.tools.builtin)
    # Auto-approve all MCP tools from the corvus bridge — these are already
    # scoped to the agent's allowed modules in the MCP config.
    if mcp_config_path is not None:
        allowed.append("mcp__corvus-tools__*")
    if allowed:
        cmd.extend(["--allowedTools", *allowed])

    # Budget
    if args.budget is not None:
        cmd.extend(["--max-budget-usd", str(args.budget)])

    # Max turns (only works with --print)
    if args.max_turns is not None:
        cmd.extend(["--max-turns", str(args.max_turns)])

    # Resume session
    if args.resume:
        cmd.extend(["--resume", args.resume])

    # Print mode (non-interactive)
    if args.print_mode:
        cmd.append("--print")

    # MCP config (domain tools + external servers)
    if mcp_config_path is not None:
        cmd.extend(["--mcp-config", str(mcp_config_path)])

    return cmd


def _start_litellm(runtime: object) -> None:
    """Start LiteLLM proxy so model routing works."""
    import asyncio

    try:
        asyncio.run(
            runtime.litellm_manager.start(  # type: ignore[attr-defined]
                Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"
            )
        )
        runtime.model_router.discover_models()  # type: ignore[attr-defined]
        logger.info(
            "LiteLLM proxy started, ANTHROPIC_BASE_URL=%s",
            os.environ.get("ANTHROPIC_BASE_URL"),
        )
    except Exception as exc:
        logger.warning("LiteLLM proxy failed to start: %s — using direct API", exc)
        print(
            f"  Warning: LiteLLM proxy not available ({exc}). Using direct API.",
            file=sys.stderr,
        )


def _stop_litellm(runtime: object) -> None:
    """Stop LiteLLM proxy on exit."""
    import asyncio

    try:
        asyncio.run(runtime.litellm_manager.stop())  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> None:
    """Entry point for corvus chat."""
    from corvus.gateway.runtime import build_runtime, ensure_dirs

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = parse_args()

    ensure_dirs()
    runtime = build_runtime()

    if args.list_agents:
        _handle_list_agents(runtime)
        return
    if args.list_models:
        _handle_list_models(runtime)
        return

    agent_name = args.agent or _pick_agent_interactive(runtime)
    claude_bin = _find_claude_binary()

    # Create per-agent workspace directory so the agent doesn't operate
    # in the corvus project root.
    from corvus.config import WORKSPACE_DIR

    agent_workspace = WORKSPACE_DIR / "agents" / agent_name
    agent_workspace.mkdir(parents=True, exist_ok=True)

    # Start LiteLLM proxy for model routing
    _start_litellm(runtime)

    # Build isolated environment (prevents global plugin/config leakage)
    env = _prepare_isolated_env(agent_name, runtime, workspace_cwd=agent_workspace)

    # Generate per-agent MCP config (domain tools + memory + external servers)
    mcp_config_path = _build_agent_mcp_config(agent_name, runtime, Path(env["HOME"]))

    cmd = _build_claude_cmd(claude_bin, runtime, agent_name, args, mcp_config_path=mcp_config_path)

    # Extract the model ID from the built command and seed settings
    model_idx = cmd.index("--model") + 1 if "--model" in cmd else -1
    if model_idx > 0:
        _seed_agent_settings(Path(env["HOME"]), cmd[model_idx])

    if args.verbose:
        # Show command with truncated system prompt for readability
        display = []
        skip_next = False
        for i, arg in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if arg == "--system-prompt" and i + 1 < len(cmd):
                display.append(f"--system-prompt '<{agent_name} prompt: {len(cmd[i + 1])} chars>'")
                skip_next = True
            else:
                display.append(arg)
        print(f"\n  {' '.join(display)}\n")
        print(f"  Isolated HOME: {env['HOME']}")

    print(f"\n  Launching Claude Code as @{agent_name}...")
    print(f"  Workspace: {agent_workspace}\n")

    try:
        result = subprocess.run(cmd, env=env, cwd=agent_workspace)
        sys.exit(result.returncode)
    finally:
        _stop_litellm(runtime)


if __name__ == "__main__":
    main()
