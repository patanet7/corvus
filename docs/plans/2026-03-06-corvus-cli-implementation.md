# Corvus CLI (`corvus chat`) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `corvus chat` — an interactive terminal REPL that talks to any Corvus agent using the real gateway runtime (memory, model routing, tools, permissions), enabling subsystem-by-subsystem QA testing without the frontend.

**Architecture:** Thin REPL over `GatewayRuntime` + `ClaudeSDKClient`. The CLI reuses `build_runtime()` and `build_backend_options()` unchanged. Two new files: `corvus/cli/chat.py` (entry point + REPL loop) and `corvus/cli/chat_render.py` (ANSI output formatting). Agent config restructure moves prompt/soul into co-located directories under `config/agents/<name>/`.

**Tech Stack:** Python 3.13, `prompt_toolkit`, `claude_agent_sdk`, FastAPI (runtime only), `rich` (ANSI formatting)

---

## Task 1: Agent Config Directory Restructure — AgentSpec + AgentRegistry

Move from flat `config/agents/<name>.yaml` + scattered `corvus/prompts/` files to co-located `config/agents/<name>/agent.yaml` directories with `soul.md` and `prompt.md` alongside.

**Files:**
- Modify: `corvus/agents/spec.py:72-101` (AgentSpec — add directory-convention loading)
- Modify: `corvus/agents/registry.py:86-109` (AgentRegistry.load — support directory-based configs)
- Test: `tests/unit/test_agent_config_restructure.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_agent_config_restructure.py`:

```python
"""Tests for directory-based agent config loading."""

import textwrap
from pathlib import Path

import pytest
import yaml

from corvus.agents.registry import AgentRegistry
from corvus.agents.spec import AgentSpec


@pytest.fixture()
def agent_dir(tmp_path: Path) -> Path:
    """Create a directory-based agent config at tmp_path/config/agents/homelab/."""
    base = tmp_path / "config" / "agents" / "homelab"
    base.mkdir(parents=True)

    # agent.yaml
    (base / "agent.yaml").write_text(
        yaml.dump(
            {
                "name": "homelab",
                "description": "Homelab management agent",
                "enabled": True,
                "models": {"complexity": "high"},
                "tools": {"builtin": ["Bash", "Read"]},
                "memory": {"own_domain": "homelab"},
            }
        )
    )
    # soul.md — convention loaded
    (base / "soul.md").write_text("You are a sysadmin who loves containers.")
    # prompt.md — convention loaded
    (base / "prompt.md").write_text("# Homelab Agent\nManage Docker containers.")
    return tmp_path / "config" / "agents"


@pytest.fixture()
def flat_agent_dir(tmp_path: Path) -> Path:
    """Create a legacy flat agent config."""
    base = tmp_path / "config" / "agents"
    base.mkdir(parents=True)
    (base / "personal.yaml").write_text(
        yaml.dump(
            {
                "name": "personal",
                "description": "Personal assistant",
                "enabled": True,
                "models": {"complexity": "medium"},
            }
        )
    )
    return base


def test_registry_loads_directory_agent(agent_dir: Path) -> None:
    reg = AgentRegistry(config_dir=agent_dir)
    reg.load()
    spec = reg.get("homelab")
    assert spec is not None
    assert spec.name == "homelab"
    assert spec.description == "Homelab management agent"


def test_registry_loads_flat_yaml(flat_agent_dir: Path) -> None:
    reg = AgentRegistry(config_dir=flat_agent_dir)
    reg.load()
    spec = reg.get("personal")
    assert spec is not None
    assert spec.name == "personal"


def test_spec_prompt_from_directory_convention(agent_dir: Path) -> None:
    """AgentSpec.prompt() loads prompt.md from agent directory by convention."""
    reg = AgentRegistry(config_dir=agent_dir)
    reg.load()
    spec = reg.get("homelab")
    assert spec is not None
    # config_dir for prompt resolution is the repo root (parent of config/agents)
    content = spec.prompt(config_dir=agent_dir.parent.parent)
    assert "Homelab Agent" in content


def test_spec_soul_from_directory_convention(agent_dir: Path) -> None:
    """AgentSpec loads soul from agent directory by convention."""
    reg = AgentRegistry(config_dir=agent_dir)
    reg.load()
    spec = reg.get("homelab")
    assert spec is not None
    assert spec.soul_file is not None
    soul_path = agent_dir.parent.parent / spec.soul_file
    assert soul_path.exists()
    assert "sysadmin" in soul_path.read_text()


def test_registry_loads_mixed_flat_and_directory(tmp_path: Path) -> None:
    """Registry handles both flat YAML and directory-based agents."""
    base = tmp_path / "config" / "agents"
    base.mkdir(parents=True)

    # Flat agent
    (base / "personal.yaml").write_text(
        yaml.dump({"name": "personal", "description": "Personal", "models": {"complexity": "medium"}})
    )

    # Directory agent
    homelab_dir = base / "homelab"
    homelab_dir.mkdir()
    (homelab_dir / "agent.yaml").write_text(
        yaml.dump({"name": "homelab", "description": "Homelab", "models": {"complexity": "high"}})
    )

    reg = AgentRegistry(config_dir=base)
    reg.load()
    assert reg.get("personal") is not None
    assert reg.get("homelab") is not None
    assert len(reg.list_all()) == 2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_agent_config_restructure.py -v`
Expected: FAIL — registry doesn't load directory-based configs yet

**Step 3: Modify AgentRegistry to support directory-based configs**

In `corvus/agents/registry.py`, update `load()` method to scan for both `*.yaml` (flat) and `<name>/agent.yaml` (directory):

```python
def load(self) -> None:
    """Load all agent specs from config_dir.

    Supports two layouts:
    - Flat: config/agents/<name>.yaml
    - Directory: config/agents/<name>/agent.yaml (with optional soul.md, prompt.md)
    """
    self._specs.clear()
    self._file_contents.clear()
    if not self._config_dir.exists():
        logger.warning("Config dir %s does not exist — no agents loaded", self._config_dir)
        return
    # Flat YAML files
    for yaml_file in sorted(self._config_dir.glob("*.yaml")):
        self._load_one(yaml_file)
    # Directory-based agents
    for subdir in sorted(self._config_dir.iterdir()):
        if not subdir.is_dir():
            continue
        agent_yaml = subdir / "agent.yaml"
        if agent_yaml.exists():
            self._load_one(agent_yaml, agent_dir=subdir)
```

Update `_load_one` to accept optional `agent_dir` and apply convention paths:

```python
def _load_one(self, path: Path, agent_dir: Path | None = None) -> bool:
    """Load a single YAML file. Returns True on success, False on skip."""
    try:
        spec = AgentSpec.from_yaml(path)
    except (yaml.YAMLError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse %s: %s", path.name, exc)
        return False
    # Convention: if loaded from a directory and soul.md/prompt.md exist, set paths
    if agent_dir is not None:
        soul_path = agent_dir / "soul.md"
        prompt_path = agent_dir / "prompt.md"
        if prompt_path.exists() and not spec.prompt_file:
            spec.prompt_file = str(prompt_path.relative_to(self._config_dir.parent.parent))
        if soul_path.exists() and not spec.soul_file:
            spec.soul_file = str(soul_path.relative_to(self._config_dir.parent.parent))
    errors = self.validate(spec)
    if errors:
        logger.warning("Invalid spec %s: %s", path.name, "; ".join(errors))
        return False
    self._specs[spec.name] = spec
    self._file_contents[spec.name] = path.read_text()
    return True
```

Also update `reload()` to scan directories the same way (same glob + iterdir pattern).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_agent_config_restructure.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/agents/registry.py tests/unit/test_agent_config_restructure.py
git commit -m "feat: support directory-based agent configs (config/agents/<name>/agent.yaml)"
```

---

## Task 2: Migrate Existing Agents to Directory Layout

Move the current flat configs + scattered prompts/souls into co-located directories.

**Files:**
- Move: `config/agents/homelab.yaml` → `config/agents/homelab/agent.yaml` (for each agent)
- Move: `corvus/prompts/homelab.md` → `config/agents/homelab/prompt.md` (for each agent)
- Move: `corvus/prompts/souls/homelab.md` → `config/agents/homelab/soul.md` (for each agent)
- Keep: `corvus/prompts/soul.md` (shared base soul — stays put)
- Modify: Each `agent.yaml` to remove `prompt_file` and `soul_file` (convention takes over)

**Step 1: Write a migration script test**

Create `tests/unit/test_agent_migration_verify.py`:

```python
"""Verify all agents loaded after directory migration."""

from pathlib import Path

import pytest

from corvus.agents.registry import AgentRegistry


EXPECTED_AGENTS = [
    "docs", "email", "finance", "general", "home",
    "homelab", "huginn", "music", "personal", "work",
]


@pytest.fixture()
def real_registry() -> AgentRegistry:
    config_dir = Path("config/agents")
    if not config_dir.exists():
        pytest.skip("config/agents not present")
    reg = AgentRegistry(config_dir=config_dir)
    reg.load()
    return reg


def test_all_agents_loaded(real_registry: AgentRegistry) -> None:
    loaded = sorted(s.name for s in real_registry.list_all())
    assert loaded == sorted(EXPECTED_AGENTS)


def test_no_prompt_file_or_soul_file_in_yaml(real_registry: AgentRegistry) -> None:
    """After migration, prompt_file/soul_file should be set by convention, not YAML."""
    for spec in real_registry.list_all():
        # Convention sets these from agent_dir — the YAML itself shouldn't have them
        # (they're auto-populated by _load_one)
        pass  # This is a sanity check — just ensure load didn't crash
```

**Step 2: Run test to verify it fails (agents still flat)**

Run: `uv run pytest tests/unit/test_agent_migration_verify.py -v`
Expected: PASS (registry already loads flat, but after migration it should still pass)

**Step 3: Execute the migration**

For each agent (`docs`, `email`, `finance`, `general`, `home`, `homelab`, `huginn`, `music`, `personal`, `work`):

```bash
# Example for homelab — repeat for all 10 agents
mkdir -p config/agents/homelab
mv config/agents/homelab.yaml config/agents/homelab/agent.yaml
cp corvus/prompts/homelab.md config/agents/homelab/prompt.md
cp corvus/prompts/souls/homelab.md config/agents/homelab/soul.md
```

Then edit each `agent.yaml` to remove `prompt_file` and `soul_file` lines (convention will find them).

**Step 4: Run tests to verify migration worked**

Run: `uv run pytest tests/unit/test_agent_migration_verify.py tests/unit/test_agent_config_restructure.py -v`
Expected: PASS

**Step 5: Update AgentsHub prompt composition**

Modify `corvus/agents/hub.py:306-346` — the soul_file and prompt_file paths now resolve through the registry's convention-set values. No changes needed if `_load_one` sets `spec.soul_file` and `spec.prompt_file` correctly. Verify by running existing tests:

Run: `uv run pytest tests/ -k "agent" -v --timeout=30`

**Step 6: Commit**

```bash
git add config/agents/ corvus/prompts/ tests/unit/test_agent_migration_verify.py
git commit -m "refactor: migrate agents to co-located directory layout"
```

---

## Task 3: Chat ANSI Renderer (`corvus/cli/chat_render.py`)

Build the terminal output formatting module. No dependencies on runtime — pure string formatting.

**Files:**
- Create: `corvus/cli/chat_render.py`
- Test: `tests/unit/test_chat_render.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_chat_render.py`:

```python
"""Tests for CLI chat ANSI rendering."""

from corvus.cli.chat_render import (
    format_agent_name,
    format_info_line,
    format_memory_event,
    format_tool_call,
    render_welcome,
)


def test_format_agent_name_includes_name() -> None:
    result = format_agent_name("homelab")
    assert "homelab" in result


def test_format_tool_call_shows_tool_and_input() -> None:
    result = format_tool_call("Bash", {"command": "docker ps"})
    assert "Bash" in result
    assert "docker ps" in result


def test_format_memory_event_shows_domain_and_content() -> None:
    result = format_memory_event("save", "homelab", "NAS IP is 10.0.0.50")
    assert "homelab" in result
    assert "NAS IP" in result


def test_format_info_line() -> None:
    result = format_info_line("Model", "claude-sonnet-4-6")
    assert "Model" in result
    assert "claude-sonnet-4-6" in result


def test_render_welcome_lists_agents() -> None:
    agents = [("homelab", "Server management"), ("finance", "Budget tracking")]
    result = render_welcome(agents)
    assert "homelab" in result
    assert "finance" in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_chat_render.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement `corvus/cli/chat_render.py`**

```python
"""ANSI terminal formatting for corvus chat CLI."""

from __future__ import annotations

# ANSI escape codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_RED = "\033[31m"

# Agent color palette (cycles for unknown agents)
_AGENT_COLORS = {
    "homelab": "\033[36m",   # cyan
    "finance": "\033[32m",   # green
    "personal": "\033[35m",  # magenta
    "work": "\033[34m",      # blue
    "email": "\033[33m",     # yellow
    "docs": "\033[37m",      # white
    "music": "\033[35m",     # magenta
    "home": "\033[36m",      # cyan
    "huginn": "\033[31m",    # red
    "general": "\033[37m",   # white
}


def _agent_color(agent: str) -> str:
    return _AGENT_COLORS.get(agent, _CYAN)


def format_agent_name(agent: str) -> str:
    """Format agent name with color for terminal display."""
    color = _agent_color(agent)
    return f"{color}{_BOLD}@{agent}{_RESET}"


def format_tool_call(tool_name: str, tool_input: dict) -> str:
    """Format a tool call for inline display."""
    summary = ""
    if "command" in tool_input:
        summary = str(tool_input["command"])[:120]
    elif "file_path" in tool_input:
        summary = str(tool_input["file_path"])
    elif "pattern" in tool_input:
        summary = str(tool_input["pattern"])
    else:
        keys = list(tool_input.keys())[:3]
        summary = ", ".join(f"{k}=..." for k in keys)
    return f"  {_DIM}[tool:{tool_name}]{_RESET} {summary}"


def format_memory_event(action: str, domain: str, content: str) -> str:
    """Format a memory save/recall event."""
    icon = "+" if action == "save" else "?"
    return f"  {_GREEN}[memory:{icon}]{_RESET} {_DIM}{domain}{_RESET} -- {content[:200]}"


def format_info_line(label: str, value: str) -> str:
    """Format a key-value info line."""
    return f"  {_BOLD}{label}:{_RESET} {value}"


def format_confirm_prompt(tool_name: str, tool_input: dict) -> str:
    """Format a confirm-gated tool prompt."""
    lines = [
        f"\n  {_YELLOW}{_BOLD}! {tool_name}{_RESET}",
    ]
    for k, v in tool_input.items():
        lines.append(f"    {_DIM}{k}:{_RESET} {str(v)[:200]}")
    lines.append(f"\n  {_DIM}[y] approve  [n] deny  [c] converse  [+note] add note:{_RESET} ")
    return "\n".join(lines)


def render_welcome(agents: list[tuple[str, str]]) -> str:
    """Render welcome screen with available agents."""
    lines = [
        f"\n  {_BOLD}Corvus Chat{_RESET}",
        f"  {_DIM}Interactive agent REPL — type /help for commands{_RESET}\n",
        f"  {_BOLD}Available agents:{_RESET}",
    ]
    for name, desc in agents:
        color = _agent_color(name)
        lines.append(f"    {color}{name:12s}{_RESET} {_DIM}{desc[:60]}{_RESET}")
    lines.append("")
    return "\n".join(lines)


def render_info(
    agent: str,
    model: str,
    backend: str,
    session_id: str,
    memory_domain: str | None = None,
) -> str:
    """Render /info output."""
    lines = [
        f"\n  {_BOLD}Session Info{_RESET}",
        format_info_line("Agent", format_agent_name(agent)),
        format_info_line("Model", model),
        format_info_line("Backend", backend),
        format_info_line("Session", session_id),
    ]
    if memory_domain:
        lines.append(format_info_line("Memory Domain", memory_domain))
    lines.append("")
    return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_chat_render.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/chat_render.py tests/unit/test_chat_render.py
git commit -m "feat: add CLI chat ANSI renderer"
```

---

## Task 4: Chat CLI Entry Point (`corvus/cli/chat.py`)

The main REPL module. Reuses `build_runtime()` and `build_backend_options()`.

**Files:**
- Create: `corvus/cli/chat.py`
- Modify: `mise.toml` (add `chat` task)
- Test: `tests/unit/test_chat_cli_parse.py`

**Step 1: Write the failing tests for argument parsing**

Create `tests/unit/test_chat_cli_parse.py`:

```python
"""Tests for corvus chat CLI argument parsing."""

from corvus.cli.chat import parse_args


def test_default_args() -> None:
    args = parse_args([])
    assert args.agent is None
    assert args.model is None
    assert args.resume is None
    assert args.budget is None
    assert args.max_turns is None
    assert args.list_agents is False
    assert args.list_models is False
    assert args.memory_debug is False


def test_agent_flag() -> None:
    args = parse_args(["--agent", "homelab"])
    assert args.agent == "homelab"


def test_model_override() -> None:
    args = parse_args(["--agent", "homelab", "--model", "ollama/qwen3:8b"])
    assert args.model == "ollama/qwen3:8b"


def test_resume_flag() -> None:
    args = parse_args(["--resume", "sess-abc123"])
    assert args.resume == "sess-abc123"


def test_budget_flag() -> None:
    args = parse_args(["--budget", "0.50"])
    assert args.budget == 0.50


def test_max_turns_flag() -> None:
    args = parse_args(["--max-turns", "10"])
    assert args.max_turns == 10


def test_list_agents_flag() -> None:
    args = parse_args(["--list-agents"])
    assert args.list_agents is True


def test_list_models_flag() -> None:
    args = parse_args(["--list-models"])
    assert args.list_models is True


def test_memory_debug_flag() -> None:
    args = parse_args(["--memory-debug"])
    assert args.memory_debug is True


def test_permission_flag() -> None:
    args = parse_args(["--permission", "default"])
    assert args.permission == "default"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_chat_cli_parse.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement `corvus/cli/chat.py`**

```python
"""corvus chat — interactive terminal REPL for Corvus agents.

Entry point: `uv run python -m corvus.cli.chat`
Or via mise: `mise run chat`

Reuses the full GatewayRuntime (memory, model routing, tools, permissions)
without the frontend or WebSocket layer.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from typing import NoReturn

from corvus.cli.chat_render import (
    format_agent_name,
    format_confirm_prompt,
    format_tool_call,
    render_info,
    render_welcome,
)
from corvus.gateway.options import (
    build_backend_options,
    resolve_backend_and_model,
)
from corvus.gateway.runtime import GatewayRuntime, build_runtime, ensure_dirs

logger = logging.getLogger("corvus-cli")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for corvus chat."""
    parser = argparse.ArgumentParser(
        prog="corvus chat",
        description="Interactive terminal REPL for Corvus agents",
    )
    parser.add_argument("--agent", type=str, default=None, help="Agent name to chat with")
    parser.add_argument("--model", type=str, default=None, help="Override model (e.g. ollama/qwen3:8b)")
    parser.add_argument("--resume", type=str, default=None, help="Resume session by ID")
    parser.add_argument("--budget", type=float, default=None, help="Spend cap in USD")
    parser.add_argument("--max-turns", type=int, default=None, help="Max conversation turns")
    parser.add_argument("--permission", type=str, default=None, help="Permission mode (default, plan, bypassPermissions)")
    parser.add_argument("--memory-debug", action="store_true", help="Show decay scores and memory seeding details")
    parser.add_argument("--list-agents", action="store_true", help="List available agents and exit")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    return parser.parse_args(argv)


def _pick_agent_interactive(runtime: GatewayRuntime) -> str:
    """Interactive agent picker when --agent is not specified."""
    agents = runtime.agent_registry.list_enabled()
    # Filter out router agent
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


def _handle_list_agents(runtime: GatewayRuntime) -> None:
    agents = runtime.agent_registry.list_enabled()
    agents = [a for a in agents if a.name != "huginn"]
    welcome_data = [(a.name, a.description.strip()) for a in agents]
    print(render_welcome(welcome_data))


def _handle_list_models(runtime: GatewayRuntime) -> None:
    models = runtime.model_router.list_models()
    print(f"\n  Available models ({len(models)}):\n")
    for m in models:
        default_tag = " (default)" if m.is_default else ""
        print(f"    {m.id:30s}  {m.backend:10s}  {m.label}{default_tag}")
    print()


async def _repl(runtime: GatewayRuntime, args: argparse.Namespace) -> None:
    """Main REPL loop."""
    from claude_agent_sdk import ClaudeSDKClient

    agent_name = args.agent or _pick_agent_interactive(runtime)
    session_id = args.resume or f"cli-{uuid.uuid4().hex[:12]}"

    backend, model = resolve_backend_and_model(runtime, agent_name, args.model)
    spec = runtime.agents_hub.get_agent(agent_name)
    memory_domain = spec.memory.own_domain if spec and spec.memory else None

    print(render_info(
        agent=agent_name,
        model=model,
        backend=backend,
        session_id=session_id,
        memory_domain=memory_domain,
    ))

    opts = build_backend_options(
        runtime=runtime,
        user="cli",
        websocket=None,
        backend_name=backend,
        active_model=model,
        agent_name=agent_name,
        session_id=session_id,
    )

    # Apply CLI-specific overrides
    if args.permission:
        opts.permission_mode = args.permission

    client_kwargs = {}
    if args.budget is not None:
        client_kwargs["max_budget_usd"] = args.budget
    if args.max_turns is not None:
        client_kwargs["max_turns"] = args.max_turns
    if args.resume:
        client_kwargs["resume"] = args.resume

    client = ClaudeSDKClient(opts, **client_kwargs)

    while True:
        try:
            user_input = input(f"\n  {format_agent_name(agent_name)} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            handled = _handle_command(user_input, runtime, agent_name, model, backend, session_id, memory_domain)
            if handled == "quit":
                break
            continue

        # Send to agent
        try:
            response = await client.query(user_input)
            async for msg in client.receive_response():
                msg_type = getattr(msg, "type", None) or type(msg).__name__
                if msg_type in ("text", "AssistantMessage"):
                    content = getattr(msg, "content", "") or getattr(msg, "text", "")
                    if content:
                        print(f"\n  {content}")
                elif msg_type in ("tool_use", "ToolUseMessage"):
                    tool_name = getattr(msg, "name", "unknown")
                    tool_input = getattr(msg, "input", {})
                    print(format_tool_call(tool_name, tool_input))
        except Exception as exc:
            print(f"\n  \033[31mError: {exc}\033[0m")


def _handle_command(
    cmd: str,
    runtime: GatewayRuntime,
    agent_name: str,
    model: str,
    backend: str,
    session_id: str,
    memory_domain: str | None,
) -> str | None:
    """Handle slash commands. Returns 'quit' to exit REPL."""
    parts = cmd.strip().split(maxsplit=2)
    command = parts[0].lower()

    if command in ("/quit", "/exit", "/q"):
        print("  Goodbye.")
        return "quit"

    if command == "/info":
        print(render_info(agent_name, model, backend, session_id, memory_domain))
        return None

    if command == "/help":
        print("""
  /agent <name>    Switch agent (new session)
  /model <id>      Switch model
  /memory search   Search memory
  /memory list     List recent memories
  /sessions        List recent sessions
  /info            Show session info
  /help            Show this help
  /quit            Exit
""")
        return None

    if command == "/memory" and len(parts) >= 2:
        sub = parts[1].lower()
        if sub == "search" and len(parts) >= 3:
            query = parts[2]
            results = runtime.memory_hub.search(query, agent_name=agent_name, limit=10)
            if not results:
                print("  No memories found.")
            else:
                for r in results:
                    print(f"  [{r.domain}] {r.content[:200]}")
            return None
        if sub == "list":
            results = runtime.memory_hub.seed_context(agent_name, limit=10)
            if not results:
                print("  No memories for this agent.")
            else:
                for r in results:
                    print(f"  [{r.domain}] {r.content[:200]}")
            return None

    print(f"  Unknown command: {command}. Type /help for available commands.")
    return None


def main() -> None:
    """Entry point for corvus chat."""
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_chat_cli_parse.py -v`
Expected: PASS

**Step 5: Add mise task**

Add to `mise.toml`:

```toml
[tasks.chat]
description = "Interactive agent REPL"
run = "uv run python -m corvus.cli.chat"
```

**Step 6: Commit**

```bash
git add corvus/cli/chat.py tests/unit/test_chat_cli_parse.py mise.toml
git commit -m "feat: add corvus chat CLI entry point with REPL loop"
```

---

## Task 5: Add `prompt_toolkit` for Escape Key + Input History

Replace bare `input()` with `prompt_toolkit` for Escape interrupt, input history, and tab completion.

**Files:**
- Modify: `corvus/cli/chat.py` (swap input() for prompt_toolkit)
- Modify: `requirements.txt` or `pyproject.toml` (add prompt_toolkit dependency)

**Step 1: Add prompt_toolkit dependency**

Run: `uv pip install prompt_toolkit`

Then add `prompt_toolkit` to the project dependencies (in `pyproject.toml` or `requirements.txt`).

**Step 2: Update the REPL input**

Replace the `input()` calls in `_repl()` and `_pick_agent_interactive()` with `prompt_toolkit`:

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings

def _create_keybindings() -> KeyBindings:
    """Create key bindings with Escape to interrupt."""
    kb = KeyBindings()

    @kb.add("escape")
    def _(event):
        """Escape key — interrupt current operation."""
        event.app.exit(exception=KeyboardInterrupt)

    return kb


async def _repl(runtime: GatewayRuntime, args: argparse.Namespace) -> None:
    session = PromptSession(
        history=InMemoryHistory(),
        key_bindings=_create_keybindings(),
    )
    # ... replace input() with session.prompt(...)
```

**Step 3: Test manually**

Run: `mise run chat --list-agents`
Expected: Lists all available agents with colored output

**Step 4: Commit**

```bash
git add corvus/cli/chat.py pyproject.toml
git commit -m "feat: add prompt_toolkit for escape key + input history"
```

---

## Task 6: Confirm-Gated Tool Flow for CLI

Build the terminal-native confirm flow: `[y] approve [n] deny [c] converse [+note] add note`.

**Files:**
- Create: `corvus/cli/chat_confirm.py`
- Test: `tests/unit/test_chat_confirm.py`

**Step 1: Write failing tests**

Create `tests/unit/test_chat_confirm.py`:

```python
"""Tests for CLI confirm-gated tool prompts."""

from unittest.mock import AsyncMock

import pytest

from corvus.cli.chat_confirm import parse_confirm_response


def test_parse_y_returns_allow() -> None:
    result = parse_confirm_response("y")
    assert result.action == "allow"
    assert result.note is None


def test_parse_n_returns_deny() -> None:
    result = parse_confirm_response("n")
    assert result.action == "deny"
    assert result.note is None


def test_parse_plus_note() -> None:
    result = parse_confirm_response("+this is important")
    assert result.action == "note"
    assert result.note == "this is important"


def test_parse_c_returns_converse() -> None:
    result = parse_confirm_response("c")
    assert result.action == "converse"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_chat_confirm.py -v`
Expected: FAIL

**Step 3: Implement `corvus/cli/chat_confirm.py`**

```python
"""Terminal-native confirm flow for gated tools."""

from __future__ import annotations

from dataclasses import dataclass

from corvus.cli.chat_render import format_confirm_prompt


@dataclass
class ConfirmResponse:
    """Parsed confirm response."""
    action: str  # "allow", "deny", "converse", "note"
    note: str | None = None


def parse_confirm_response(raw: str) -> ConfirmResponse:
    """Parse user's response to a confirm prompt."""
    text = raw.strip().lower()
    if text in ("y", "yes"):
        return ConfirmResponse(action="allow")
    if text in ("n", "no"):
        return ConfirmResponse(action="deny")
    if text in ("c", "converse"):
        return ConfirmResponse(action="converse")
    if text.startswith("+"):
        return ConfirmResponse(action="note", note=text[1:].strip())
    # Default: treat as deny
    return ConfirmResponse(action="deny", note=f"Unrecognized input: {raw}")


def terminal_confirm(tool_name: str, tool_input: dict) -> ConfirmResponse:
    """Show confirm prompt in terminal and get user response."""
    print(format_confirm_prompt(tool_name, tool_input))
    try:
        raw = input("  > ")
    except (EOFError, KeyboardInterrupt):
        return ConfirmResponse(action="deny", note="User interrupted")
    return parse_confirm_response(raw)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_chat_confirm.py -v`
Expected: PASS

**Step 5: Wire into `_build_can_use_tool` in chat.py**

In `corvus/cli/chat.py`, create a CLI-specific `can_use_tool` callback that uses `terminal_confirm()` instead of the WebSocket confirm queue:

```python
from corvus.cli.chat_confirm import terminal_confirm, ConfirmResponse
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

async def _cli_can_use_tool(tool_name, tool_input, context):
    # ... evaluate permission same as options.py ...
    # If confirm-gated:
    response = terminal_confirm(tool_name, tool_input)
    if response.action == "allow":
        return PermissionResultAllow()
    return PermissionResultDeny(message=response.note or "User denied")
```

**Step 6: Commit**

```bash
git add corvus/cli/chat_confirm.py tests/unit/test_chat_confirm.py corvus/cli/chat.py
git commit -m "feat: add terminal confirm-gated tool flow for CLI"
```

---

## Task 7: Skills Isolation — Per-Agent Workspace Skills

Wire `prepare_agent_workspace` to copy agent-specific skills into the workspace's `.claude/skills/` directory.

**Files:**
- Modify: `corvus/gateway/workspace_runtime.py:74-118`
- Test: `tests/unit/test_workspace_skills.py`

**Step 1: Write failing tests**

Create `tests/unit/test_workspace_skills.py`:

```python
"""Tests for per-agent skills copying into workspace."""

from pathlib import Path

import pytest
import yaml

from corvus.gateway.workspace_runtime import copy_agent_skills


@pytest.fixture()
def agent_config_dir(tmp_path: Path) -> Path:
    """Create agent config with skills."""
    agent_dir = tmp_path / "config" / "agents" / "homelab"
    agent_dir.mkdir(parents=True)
    skills_dir = agent_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "docker-operations.md").write_text("# Docker Operations\nHow to manage containers.")
    (skills_dir / "loki-queries.md").write_text("# Loki Queries\nHow to write LogQL.")
    return tmp_path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_copies_agent_skills_to_workspace(agent_config_dir: Path, workspace: Path) -> None:
    copy_agent_skills(
        agent_name="homelab",
        config_dir=agent_config_dir,
        workspace_dir=workspace,
    )
    skills_dest = workspace / ".claude" / "skills"
    assert skills_dest.is_dir()
    assert (skills_dest / "docker-operations.md").exists()
    assert (skills_dest / "loki-queries.md").exists()


def test_no_skills_dir_is_noop(tmp_path: Path, workspace: Path) -> None:
    """Agent with no skills/ dir — nothing copied, no error."""
    config_dir = tmp_path / "config"
    (config_dir / "agents" / "personal").mkdir(parents=True)
    copy_agent_skills("personal", config_dir, workspace)
    assert not (workspace / ".claude" / "skills").exists()


def test_shared_skills_copied(tmp_path: Path, workspace: Path) -> None:
    """Shared skills from config/skills/shared/ are copied if agent opts in."""
    config_dir = tmp_path
    shared_dir = config_dir / "config" / "skills" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "obsidian-vault.md").write_text("# Obsidian Vault\nHow to use vault.")

    agent_dir = config_dir / "config" / "agents" / "homelab"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        yaml.dump({
            "name": "homelab",
            "description": "Homelab",
            "models": {"complexity": "high"},
            "metadata": {"shared_skills": ["obsidian-vault"]},
        })
    )

    copy_agent_skills(
        agent_name="homelab",
        config_dir=config_dir,
        workspace_dir=workspace,
        shared_skills=["obsidian-vault"],
    )
    assert (workspace / ".claude" / "skills" / "obsidian-vault.md").exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_workspace_skills.py -v`
Expected: FAIL

**Step 3: Implement `copy_agent_skills` in `workspace_runtime.py`**

Add to `corvus/gateway/workspace_runtime.py`:

```python
def copy_agent_skills(
    agent_name: str,
    config_dir: Path,
    workspace_dir: Path,
    shared_skills: list[str] | None = None,
) -> None:
    """Copy agent-specific and shared skills into workspace .claude/skills/."""
    skills_dest = workspace_dir / ".claude" / "skills"

    # Agent-specific skills
    agent_skills_dir = config_dir / "config" / "agents" / agent_name / "skills"
    if agent_skills_dir.is_dir():
        skills_dest.mkdir(parents=True, exist_ok=True)
        for skill_file in agent_skills_dir.glob("*.md"):
            shutil.copy2(skill_file, skills_dest / skill_file.name)

    # Shared skills
    if shared_skills:
        shared_dir = config_dir / "config" / "skills" / "shared"
        if shared_dir.is_dir():
            skills_dest.mkdir(parents=True, exist_ok=True)
            for skill_name in shared_skills:
                src = shared_dir / f"{skill_name}.md"
                if src.exists():
                    shutil.copy2(src, skills_dest / src.name)
                else:
                    logger.warning("Shared skill '%s' not found at %s", skill_name, src)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_workspace_skills.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/gateway/workspace_runtime.py tests/unit/test_workspace_skills.py
git commit -m "feat: copy per-agent and shared skills into workspace"
```

---

## Task 8: Integration Smoke Test

Verify the full stack boots and parses args correctly without external dependencies.

**Files:**
- Test: `tests/unit/test_chat_integration_smoke.py`

**Step 1: Write the smoke test**

```python
"""Smoke tests for corvus chat CLI integration."""

import subprocess
import sys

import pytest


def test_chat_help_exits_zero() -> None:
    """corvus chat --help exits 0 and shows usage."""
    result = subprocess.run(
        [sys.executable, "-m", "corvus.cli.chat", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Interactive terminal REPL" in result.stdout


def test_chat_module_imports() -> None:
    """All chat modules import without error."""
    result = subprocess.run(
        [sys.executable, "-c", "from corvus.cli.chat import parse_args; from corvus.cli.chat_render import render_welcome; from corvus.cli.chat_confirm import parse_confirm_response"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
```

**Step 2: Run the smoke test**

Run: `uv run pytest tests/unit/test_chat_integration_smoke.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/unit/test_chat_integration_smoke.py
git commit -m "test: add CLI chat integration smoke tests"
```

---

## Task 9: Run Full Test Suite + Verify No Regressions

**Step 1: Run all existing tests**

Run: `uv run pytest tests/ -v --timeout=60 2>&1 | tee tests/output/$(date +%Y%m%d-%H%M%S)_test_chat_cli_results.log`

Expected: All existing tests pass + all new tests pass

**Step 2: Run lint**

Run: `mise run lint`

Expected: No lint errors in new files

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "chore: finalize corvus chat CLI implementation"
```

---

## Summary of Deliverables

| # | Deliverable | New Files | Modified Files |
|---|---|---|---|
| 1 | Directory-based agent config | `tests/unit/test_agent_config_restructure.py` | `corvus/agents/registry.py` |
| 2 | Agent migration | `tests/unit/test_agent_migration_verify.py` | `config/agents/*/` |
| 3 | ANSI renderer | `corvus/cli/chat_render.py`, `tests/unit/test_chat_render.py` | — |
| 4 | CLI entry point | `corvus/cli/chat.py`, `tests/unit/test_chat_cli_parse.py` | `mise.toml` |
| 5 | prompt_toolkit | — | `corvus/cli/chat.py`, `pyproject.toml` |
| 6 | Confirm flow | `corvus/cli/chat_confirm.py`, `tests/unit/test_chat_confirm.py` | `corvus/cli/chat.py` |
| 7 | Skills isolation | `tests/unit/test_workspace_skills.py` | `corvus/gateway/workspace_runtime.py` |
| 8 | Smoke tests | `tests/unit/test_chat_integration_smoke.py` | — |
| 9 | Full regression | — | — |
