"""corvus chat -- interactive terminal REPL for Corvus agents.

Entry point: ``uv run python -m corvus.cli.chat``
Or via mise: ``mise run chat``

Reuses the full GatewayRuntime (memory, model routing, tools, permissions)
without the frontend or WebSocket layer.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

logger = logging.getLogger("corvus-cli")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for corvus chat."""
    parser = argparse.ArgumentParser(
        prog="corvus chat",
        description="Interactive terminal REPL for Corvus agents",
    )
    parser.add_argument(
        "--agent", type=str, default=None, help="Agent name to chat with"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override model (e.g. ollama/qwen3:8b)",
    )
    parser.add_argument(
        "--resume", type=str, default=None, help="Resume session by ID"
    )
    parser.add_argument(
        "--budget", type=float, default=None, help="Spend cap in USD"
    )
    parser.add_argument(
        "--max-turns", type=int, default=None, help="Max conversation turns"
    )
    parser.add_argument(
        "--permission", type=str, default=None, help="Permission mode"
    )
    parser.add_argument(
        "--memory-debug",
        action="store_true",
        help="Show decay scores and memory seeding details",
    )
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
    return parser.parse_args(argv)


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
        print(
            f"  Unknown agent '{choice}'. "
            f"Try one of: {', '.join(a.name for a in agents)}"
        )


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


def _handle_command(
    cmd: str,
    runtime: object,
    agent_name: str,
    model: str,
    backend: str,
    session_id: str,
    memory_domain: str | None,
) -> str | None:
    """Handle slash commands. Returns 'quit' to exit REPL."""
    from corvus.cli.chat_render import render_info

    parts = cmd.strip().split(maxsplit=2)
    command = parts[0].lower()

    if command in ("/quit", "/exit", "/q"):
        print("  Goodbye.")
        return "quit"

    if command == "/info":
        print(
            render_info(agent_name, model, backend, session_id, memory_domain)
        )
        return None

    if command == "/help":
        print(
            """
  /agent <name>    Switch agent (new session)
  /model <id>      Switch model
  /memory search   Search memory
  /memory list     List recent memories
  /sessions        List recent sessions
  /info            Show session info
  /help            Show this help
  /quit            Exit
"""
        )
        return None

    if command == "/memory" and len(parts) >= 2:
        sub = parts[1].lower()
        if sub == "search" and len(parts) >= 3:
            query = parts[2]
            results = runtime.memory_hub.search(  # type: ignore[attr-defined]
                query, agent_name=agent_name, limit=10
            )
            if not results:
                print("  No memories found.")
            else:
                for r in results:
                    print(f"  [{r.domain}] {r.content[:200]}")
            return None
        if sub == "list":
            results = runtime.memory_hub.seed_context(  # type: ignore[attr-defined]
                agent_name, limit=10
            )
            if not results:
                print("  No memories for this agent.")
            else:
                for r in results:
                    print(f"  [{r.domain}] {r.content[:200]}")
            return None

    print(
        f"  Unknown command: {command}. Type /help for available commands."
    )
    return None


async def _repl(runtime: object, args: argparse.Namespace) -> None:
    """Main REPL loop."""
    from claude_agent_sdk import ClaudeSDKClient

    from corvus.cli.chat_render import format_agent_name, format_tool_call, render_info
    from corvus.gateway.options import build_backend_options, resolve_backend_and_model

    agent_name = args.agent or _pick_agent_interactive(runtime)
    session_id = args.resume or f"cli-{uuid.uuid4().hex[:12]}"

    backend, model = resolve_backend_and_model(runtime, agent_name, args.model)
    spec = runtime.agents_hub.get_agent(agent_name)  # type: ignore[attr-defined]
    memory_domain = spec.memory.own_domain if spec and spec.memory else None

    print(
        render_info(
            agent=agent_name,
            model=model,
            backend=backend,
            session_id=session_id,
            memory_domain=memory_domain,
        )
    )

    opts = build_backend_options(
        runtime=runtime,
        user="cli",
        websocket=None,
        backend_name=backend,
        active_model=model,
        agent_name=agent_name,
        session_id=session_id,
    )

    if args.permission:
        opts.permission_mode = args.permission

    client_kwargs: dict = {}
    if args.budget is not None:
        client_kwargs["max_budget_usd"] = args.budget
    if args.max_turns is not None:
        client_kwargs["max_turns"] = args.max_turns
    if args.resume:
        client_kwargs["resume"] = args.resume

    client = ClaudeSDKClient(opts, **client_kwargs)

    while True:
        try:
            user_input = input(
                f"\n  {format_agent_name(agent_name)} > "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            handled = _handle_command(
                user_input,
                runtime,
                agent_name,
                model,
                backend,
                session_id,
                memory_domain,
            )
            if handled == "quit":
                break
            continue

        try:
            response = await client.query(user_input)
            async for msg in client.receive_response():
                msg_type = getattr(msg, "type", None) or type(msg).__name__
                if msg_type in ("text", "AssistantMessage"):
                    content = getattr(msg, "content", "") or getattr(
                        msg, "text", ""
                    )
                    if content:
                        print(f"\n  {content}")
                elif msg_type in ("tool_use", "ToolUseMessage"):
                    tool_name = getattr(msg, "name", "unknown")
                    tool_input = getattr(msg, "input", {})
                    print(format_tool_call(tool_name, tool_input))
        except Exception as exc:
            print(f"\n  \033[31mError: {exc}\033[0m")


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

    asyncio.run(_repl(runtime, args))


if __name__ == "__main__":
    main()
