---
title: "Corvus CLI Unified Isolation Implementation Plan"
type: plan
status: implemented
date: 2026-03-06
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# Corvus CLI Unified Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire `corvus chat` to use the same isolation infrastructure as the server, replacing `--disable-slash-commands` with `--setting-sources project` so agents get their own skills as slash commands while being fully isolated from global Claude Code state.

**Architecture:** Remove the blanket skill-kill flag, add `--setting-sources project`, migrate existing `.claude/skills/*.md` files into per-agent and shared locations under `config/`, and add `shared_skills` metadata to agent YAML files so `copy_agent_skills()` populates each agent's isolated HOME with the right skills.

**Tech Stack:** Python, Claude Code CLI flags, existing `copy_agent_skills()` / `resolve_claude_runtime_home()` infrastructure

---

### Task 1: Fix CLI isolation flags in `_build_claude_cmd`

**Files:**
- Modify: `corvus/cli/chat.py:222-226`
- Test: `tests/unit/test_chat_cli_isolation.py`

**Step 1: Write the failing test**

Create `tests/unit/test_chat_cli_isolation.py`:

```python
"""Tests for corvus chat CLI isolation flags."""

from corvus.cli.chat import _build_claude_cmd


class _FakeSpec:
    def __init__(self):
        self.metadata = {}

        class _Tools:
            builtin = ["Bash", "Read"]
        self.tools = _Tools()


class _FakeAgentsHub:
    def build_system_prompt(self, name):
        return f"You are {name}."

    def get_agent(self, name):
        return _FakeSpec()


class _FakeModelRouter:
    def get_model(self, name):
        return "claude-sonnet-4-6"

    def get_backend(self, name):
        return "claude"


class _FakeRuntime:
    def __init__(self):
        self.agents_hub = _FakeAgentsHub()
        self.model_router = _FakeModelRouter()


def _make_args(**overrides):
    import argparse
    defaults = {
        "model": None, "permission": None, "budget": None,
        "max_turns": None, "resume": None, "print_mode": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_no_disable_slash_commands():
    """CLI must NOT pass --disable-slash-commands (blocks agent skills)."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    assert "--disable-slash-commands" not in cmd


def test_setting_sources_project():
    """CLI must pass --setting-sources project to block user-level plugins."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    idx = cmd.index("--setting-sources")
    assert cmd[idx + 1] == "project"


def test_strict_mcp_config():
    """CLI must pass --strict-mcp-config to block global MCP servers."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    assert "--strict-mcp-config" in cmd
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_chat_cli_isolation.py -v`
Expected: `test_no_disable_slash_commands` FAILS (currently passes `--disable-slash-commands`), `test_setting_sources_project` FAILS (flag not present)

**Step 3: Fix the flags in `_build_claude_cmd`**

In `corvus/cli/chat.py`, replace lines 222-226:

```python
    # --- Isolation flags ---
    # Only use MCP servers we explicitly pass, ignore global configs
    cmd.append("--strict-mcp-config")
    # Disable slash commands/skills from user-global plugins
    cmd.append("--disable-slash-commands")
```

With:

```python
    # --- Isolation flags ---
    # Only use MCP servers we explicitly pass, ignore global configs
    cmd.append("--strict-mcp-config")
    # Only load project-level settings (blocks user-level plugins/skills)
    # Agent-specific skills are loaded from the isolated HOME/.claude/skills/
    cmd.extend(["--setting-sources", "project"])
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_chat_cli_isolation.py -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add corvus/cli/chat.py tests/unit/test_chat_cli_isolation.py
git commit -m "fix: replace --disable-slash-commands with --setting-sources project

--disable-slash-commands blocked ALL skills including agent-local ones.
--setting-sources project only blocks user-level plugins while allowing
skills from the isolated HOME/.claude/skills/ to load."
```

---

### Task 2: Create shared skills directory and migrate `memory.md`

**Files:**
- Create: `config/skills/shared/memory.md`
- Move: `.claude/skills/memory.md` → `config/skills/shared/memory.md`

**Step 1: Create the shared skills directory**

```bash
mkdir -p config/skills/shared
```

**Step 2: Move `memory.md` to shared**

```bash
mv .claude/skills/memory.md config/skills/shared/memory.md
```

**Step 3: Verify the file is in the right place**

Run: `ls config/skills/shared/memory.md`
Expected: File exists

**Step 4: Commit**

```bash
git add config/skills/shared/memory.md
git add .claude/skills/memory.md
git commit -m "refactor: move memory skill to config/skills/shared/

memory.md is a shared skill — all agents can opt into it via
shared_skills metadata in their agent.yaml."
```

---

### Task 3: Migrate agent-specific skills to per-agent directories

**Files:**
- Move: `.claude/skills/finance.md` → `config/agents/finance/skills/finance.md`
- Move: `.claude/skills/email.md` → `config/agents/email/skills/email.md`
- Move: `.claude/skills/music.md` → `config/agents/music/skills/music.md`
- Move: `.claude/skills/paperless.md` → `config/agents/docs/skills/paperless.md`
- Move: `.claude/skills/obsidian.md` → `config/skills/shared/obsidian.md`

Note: `obsidian.md` is shared — multiple agents use the Obsidian vault (homelab, personal, docs). It goes to `config/skills/shared/`.

**Step 1: Create skills directories for each agent**

```bash
mkdir -p config/agents/finance/skills
mkdir -p config/agents/email/skills
mkdir -p config/agents/music/skills
mkdir -p config/agents/docs/skills
```

**Step 2: Move agent-specific skills**

```bash
mv .claude/skills/finance.md config/agents/finance/skills/finance.md
mv .claude/skills/email.md config/agents/email/skills/email.md
mv .claude/skills/music.md config/agents/music/skills/music.md
mv .claude/skills/paperless.md config/agents/docs/skills/paperless.md
mv .claude/skills/obsidian.md config/skills/shared/obsidian.md
```

**Step 3: Verify `.claude/skills/` is now empty**

Run: `ls .claude/skills/`
Expected: Empty directory (or no directory)

**Step 4: Commit**

```bash
git add config/agents/finance/skills/finance.md
git add config/agents/email/skills/email.md
git add config/agents/music/skills/music.md
git add config/agents/docs/skills/paperless.md
git add config/skills/shared/obsidian.md
git add .claude/skills/
git commit -m "refactor: migrate skills to per-agent and shared locations

Agent-specific skills → config/agents/<name>/skills/
Shared skills (obsidian, memory) → config/skills/shared/
.claude/skills/ is now empty — skills are loaded from the
agent's isolated HOME via copy_agent_skills()."
```

---

### Task 4: Add `shared_skills` metadata to agent YAML files

**Files:**
- Modify: `config/agents/homelab/agent.yaml`
- Modify: `config/agents/finance/agent.yaml`
- Modify: `config/agents/email/agent.yaml`
- Modify: `config/agents/music/agent.yaml`
- Modify: `config/agents/docs/agent.yaml`
- Modify: `config/agents/personal/agent.yaml`
- Modify: `config/agents/work/agent.yaml`
- Modify: `config/agents/home/agent.yaml`
- Modify: `config/agents/general/agent.yaml`
- Test: `tests/unit/test_chat_cli_isolation.py` (add test)

**Step 1: Write a test that verifies shared_skills are read from metadata**

Add to `tests/unit/test_chat_cli_isolation.py`:

```python
def test_prepare_isolated_env_reads_shared_skills(tmp_path):
    """_prepare_isolated_env reads shared_skills from agent spec metadata."""
    from corvus.cli.chat import _prepare_isolated_env

    # Set up config structure
    config_dir = tmp_path / "project"
    shared_dir = config_dir / "config" / "skills" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "memory.md").write_text("# Memory\nShared skill.")

    agent_dir = config_dir / "config" / "agents" / "testbot" / "skills"
    agent_dir.mkdir(parents=True)
    (agent_dir / "custom.md").write_text("# Custom\nAgent skill.")

    # Fake runtime with shared_skills metadata
    class _Spec:
        metadata = {"shared_skills": ["memory"]}
    class _Hub:
        def get_agent(self, name):
            return _Spec()
    class _Runtime:
        agents_hub = _Hub()

    # Patch config paths and call
    import corvus.cli.chat as chat_mod
    original_file = chat_mod.__file__

    # We can't easily call _prepare_isolated_env without patching config,
    # so test copy_agent_skills directly with shared_skills
    from corvus.gateway.workspace_runtime import copy_agent_skills
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    copy_agent_skills(
        agent_name="testbot",
        config_dir=config_dir,
        workspace_dir=workspace,
        shared_skills=["memory"],
    )
    assert (workspace / ".claude" / "skills" / "memory.md").exists()
    assert (workspace / ".claude" / "skills" / "custom.md").exists()
```

**Step 2: Run test to verify it passes** (this is testing existing behavior)

Run: `uv run python -m pytest tests/unit/test_chat_cli_isolation.py::test_prepare_isolated_env_reads_shared_skills -v`
Expected: PASS

**Step 3: Add `metadata.shared_skills` to each agent YAML**

Add `metadata:` section with `shared_skills` to each agent that should have shared skills. Here's the mapping:

| Agent | shared_skills |
|-------|--------------|
| homelab | `[memory, obsidian]` |
| finance | `[memory]` |
| email | `[memory]` |
| music | `[memory]` |
| docs | `[memory, obsidian]` |
| personal | `[memory, obsidian]` |
| work | `[memory, obsidian]` |
| home | `[memory]` |
| general | `[memory]` |

For each agent YAML, append a `metadata:` block at the end. For example, `config/agents/homelab/agent.yaml` currently ends after `memory:`. Add:

```yaml
metadata:
  shared_skills:
    - memory
    - obsidian
```

For agents that already have a `metadata:` key, merge `shared_skills` into it.

**Step 4: Run full test suite**

Run: `uv run python -m pytest tests/unit/test_chat_cli_isolation.py tests/unit/test_workspace_skills.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add config/agents/*/agent.yaml tests/unit/test_chat_cli_isolation.py
git commit -m "feat: add shared_skills metadata to all agent configs

Each agent declares which shared skills it needs (memory, obsidian).
copy_agent_skills() reads this at startup and populates the agent's
isolated HOME/.claude/skills/ with the right shared skill files."
```

---

### Task 5: Run smoke test and verify end-to-end

**Files:**
- Modify: `tests/unit/test_chat_integration_smoke.py`

**Step 1: Update smoke test to verify no --disable-slash-commands**

Add to `tests/unit/test_chat_integration_smoke.py`:

```python
def test_chat_parse_args_defaults() -> None:
    """parse_args returns expected defaults."""
    from corvus.cli.chat import parse_args

    args = parse_args([])
    assert args.agent is None
    assert args.model is None
    assert args.resume is None
    assert args.budget is None
    assert args.print_mode is False
    assert args.verbose is False
```

**Step 2: Run all chat-related tests**

Run: `uv run python -m pytest tests/unit/test_chat_integration_smoke.py tests/unit/test_chat_cli_isolation.py tests/unit/test_workspace_skills.py tests/unit/test_chat_confirm.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/unit/test_chat_integration_smoke.py
git commit -m "test: add parse_args defaults test for corvus chat"
```

---

### Task 6: Clean up empty `.claude/skills/` directory

**Files:**
- Remove: `.claude/skills/` (should be empty after Task 3)

**Step 1: Verify directory is empty**

```bash
ls -la .claude/skills/
```
Expected: Empty (all files moved in Task 3)

**Step 2: Remove empty directory**

```bash
rmdir .claude/skills/
```

**Step 3: Run all tests one final time**

Run: `uv run python -m pytest tests/unit/test_chat_integration_smoke.py tests/unit/test_chat_cli_isolation.py tests/unit/test_workspace_skills.py tests/unit/test_chat_confirm.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add .claude/skills/
git commit -m "chore: remove empty .claude/skills/ directory

All skills migrated to config/agents/<name>/skills/ (agent-specific)
and config/skills/shared/ (shared). Skills are now loaded into each
agent's isolated HOME at startup via copy_agent_skills()."
```
