"""corvus chat -- launch Claude Code CLI with Corvus agent configuration.

Entry point: ``uv run python -m corvus.cli.chat``
Or via mise: ``mise run chat``

Builds the full GatewayRuntime (memory, model routing, tools, permissions),
resolves agent configuration, then launches the ``claude`` CLI binary in an
isolated environment with the agent's system prompt, model, and permissions.

The model router (LiteLLM proxy) runs on localhost:4000 and the CLI
inherits ANTHROPIC_BASE_URL so all requests route through it.

A Unix socket tool server runs alongside the agent subprocess, providing
tool access via JWT-authenticated requests. The agent workspace contains
CLAUDE.md (domain instructions, siblings, memory seeds) and skill scripts
that talk to the tool server. Credentials never leave the parent process.

Environment isolation prevents the claude binary from reading the user's
global ~/.claude/ (plugins, settings, MCP configs). Each agent gets its
own scoped runtime home under .data/claude-home/.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("corvus-cli")


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


# Sensitive env vars stripped from agent subprocess (credentials stay in tool server).
_SENSITIVE_VARS = [
    "HA_URL", "HA_TOKEN",
    "OBSIDIAN_URL", "OBSIDIAN_API_KEY",
    "PAPERLESS_URL", "PAPERLESS_API_TOKEN",
    "FIREFLY_URL", "FIREFLY_API_TOKEN",
    "GMAIL_TOKEN", "GMAIL_CREDENTIALS",
    "YAHOO_APP_PASSWORD",
]


def _prepare_isolated_env(
    agent_name: str,
    runtime: object,
    tool_socket: str | None = None,
    tool_token: str | None = None,
) -> dict[str, str]:
    """Build an isolated environment for the claude subprocess.

    Prevents the claude binary from reading the user's global ~/.claude/
    (plugins, settings, MCP configs). Each agent gets its own scoped
    runtime home under .data/claude-home/.

    Tool server env vars (CORVUS_TOOL_SOCKET, CORVUS_TOOL_TOKEN) are
    injected so skill scripts can reach the parent-process tool server.
    Service credentials are stripped — they stay in the tool server process.
    """
    from corvus.config import CLAUDE_CONFIG_TEMPLATE, CLAUDE_RUNTIME_HOME
    from corvus.gateway.options import resolve_claude_runtime_home

    # Start with current env (inherits ANTHROPIC_BASE_URL from LiteLLM)
    env = dict(os.environ)

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

    # Override env to isolate claude from user-global state.
    env["HOME"] = str(runtime_home)
    env["CLAUDE_CONFIG_DIR"] = str(claude_config)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["XDG_STATE_HOME"] = str(xdg_state)
    env["XDG_DATA_HOME"] = str(xdg_data)

    # Tool server env vars for skill scripts
    if tool_socket:
        env["CORVUS_TOOL_SOCKET"] = tool_socket
    if tool_token:
        env["CORVUS_TOOL_TOKEN"] = tool_token

    # Strip service credentials — they stay in the tool server process
    for var in _SENSITIVE_VARS:
        env.pop(var, None)

    return env


def _build_claude_cmd(
    claude_bin: str,
    runtime: object,
    agent_name: str,
    args: argparse.Namespace,
    system_prompt: str,
) -> list[str]:
    """Build the full claude CLI command from agent configuration.

    Uses --system-prompt to replace Claude Code's defaults with Corvus
    identity and personality. Domain instructions, siblings, and memory
    context are delivered via CLAUDE.md in the workspace. Tools are
    delivered via skills with scripts that talk to the Unix socket server.
    """
    from corvus.gateway.options import resolve_backend_and_model
    from corvus.permissions import normalize_permission_mode

    cmd: list[str] = [claude_bin]

    # --- Isolation flags ---
    # Only load project-level settings (blocks user-level plugins/skills).
    # Agent-specific skills are loaded from the workspace .claude/skills/
    cmd.extend(["--setting-sources", "project"])

    # System prompt — minimal (soul + identity + agent soul only).
    # Appended to Claude Code's built-in defaults rather than replacing them.
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

    # Allowed tools — builtin from spec + Bash(python *) for skill scripts
    allowed: list[str] = []
    if spec and spec.tools.builtin:
        allowed.extend(spec.tools.builtin)
    allowed.append("Bash(python *)")
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
    import asyncio

    from corvus.cli.compose_claude_md import compose_claude_md
    from corvus.cli.compose_system_prompt import compose_system_prompt
    from corvus.cli.tool_server import ToolServer
    from corvus.cli.tool_token import create_token
    from corvus.config import WORKSPACE_DIR
    from corvus.gateway.runtime import build_runtime, ensure_dirs
    from corvus.gateway.workspace_runtime import copy_agent_skills

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

    agent_workspace = WORKSPACE_DIR / "agents" / agent_name
    agent_workspace.mkdir(parents=True, exist_ok=True)

    # Start LiteLLM proxy for model routing
    _start_litellm(runtime)

    # --- Tool server setup ---
    spec = runtime.agents_hub.get_agent(agent_name)  # type: ignore[attr-defined]
    module_configs: dict[str, dict] = {}
    if spec and hasattr(spec.tools, "modules") and spec.tools.modules:
        module_configs = dict(spec.tools.modules)

    memory_domain = spec.memory.own_domain if spec and spec.memory else "shared"

    secret = os.urandom(32)
    socket_path = str(agent_workspace / ".corvus.sock")
    token = create_token(
        secret=secret,
        agent=agent_name,
        modules=list(module_configs.keys()) + ["memory"],
        ttl_seconds=86400,  # 24h — session-scoped, server stops on exit
    )

    tool_server = ToolServer(
        secret=secret,
        socket_path=socket_path,
        module_configs=module_configs,
        agent_name=agent_name,
        memory_domain=memory_domain,
    )
    loop = asyncio.new_event_loop()
    loop.run_until_complete(tool_server.start())

    # --- Compose system prompt (minimal: soul + identity + agent soul) ---
    config_dir = Path(__file__).resolve().parent.parent.parent
    agent_soul_content = None
    if spec and getattr(spec, "soul_file", None):
        soul_path = config_dir / spec.soul_file
        if soul_path.exists():
            agent_soul_content = soul_path.read_text()

    system_prompt = compose_system_prompt(
        config_dir=config_dir,
        agent_name=agent_name,
        agent_soul_content=agent_soul_content,
    )

    # --- Write CLAUDE.md to workspace ---
    enabled = runtime.agent_registry.list_enabled()  # type: ignore[attr-defined]
    siblings = [
        (a.name, a.description.strip())
        for a in enabled
        if a.name != agent_name and a.name != "huginn"
    ]

    memory_lines: list[str] = []
    try:
        records = runtime.agents_hub.memory_hub.seed_context(agent_name, limit=15)  # type: ignore[attr-defined]
        for r in records:
            tag_str = f" [{', '.join(r.tags)}]" if r.tags else ""
            prefix = "[evergreen] " if r.importance >= 0.9 else ""
            memory_lines.append(f"- {prefix}({r.domain}) {r.content[:300]}{tag_str}")
    except Exception as exc:
        logger.warning("Memory seed failed: %s", exc)

    claude_md_content = compose_claude_md(
        spec=spec,
        config_dir=config_dir,
        siblings=siblings,
        memory_lines=memory_lines,
        memory_domain=memory_domain,
    )
    (agent_workspace / "CLAUDE.md").write_text(claude_md_content, encoding="utf-8")

    # --- Build isolated environment ---
    env = _prepare_isolated_env(
        agent_name,
        runtime,
        tool_socket=socket_path,
        tool_token=token,
    )

    # --- Copy skills (tool modules + agent + shared) ---
    copy_agent_skills(
        agent_name=agent_name,
        config_dir=config_dir,
        workspace_dir=agent_workspace,
        shared_skills=(
            spec.metadata.get("shared_skills")
            if spec and isinstance(spec.metadata, dict)
            else None
        ),
        tool_modules=list(module_configs.keys()),
    )

    # --- Build command ---
    cmd = _build_claude_cmd(claude_bin, runtime, agent_name, args, system_prompt=system_prompt)

    if args.verbose:
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
        print(f"  Tool socket: {socket_path}")

    print(f"\n  Launching Claude Code as @{agent_name}...")
    print(f"  Workspace: {agent_workspace}\n")

    try:
        result = subprocess.run(cmd, env=env, cwd=agent_workspace)
        sys.exit(result.returncode)
    finally:
        loop.run_until_complete(tool_server.stop())
        loop.close()
        _stop_litellm(runtime)


if __name__ == "__main__":
    main()
