"""Tests for corvus chat CLI isolation flags."""

import argparse

from corvus.cli.chat import _build_claude_cmd


class _FakeSpec:
    def __init__(self):
        self.metadata = {}

        class _Tools:
            builtin = ["Bash", "Read"]
        self.tools = _Tools()


class _FakeAgentsHub:
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
    defaults = {
        "model": None, "permission": None, "budget": None,
        "max_turns": None, "resume": None, "print_mode": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_no_disable_slash_commands():
    """CLI must NOT pass --disable-slash-commands (blocks agent skills)."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt="You are homelab.",
    )
    assert "--disable-slash-commands" not in cmd


def test_setting_sources_user_project():
    """CLI must pass --setting-sources user,project to load isolated settings."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt="You are homelab.",
    )
    idx = cmd.index("--setting-sources")
    assert cmd[idx + 1] == "user,project"


def test_no_strict_mcp_config():
    """CLI must NOT pass --strict-mcp-config (no MCP servers used)."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt="You are homelab.",
    )
    assert "--strict-mcp-config" not in cmd


def test_uses_system_prompt():
    """CLI must use --system-prompt to replace CC defaults with Corvus identity."""
    runtime = _FakeRuntime()
    prompt = "You are the homelab agent."
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt=prompt,
    )
    assert "--system-prompt" in cmd
    idx = cmd.index("--system-prompt")
    assert cmd[idx + 1] == prompt
    assert "--append-system-prompt" not in cmd


def test_no_mcp_config():
    """CLI must NOT pass --mcp-config (tools delivered via skills/socket)."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt="You are homelab.",
    )
    assert "--mcp-config" not in cmd


def test_bash_python_in_allowed_tools():
    """CLI must include Bash(python *) in --allowedTools for skill scripts."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt="You are homelab.",
    )
    idx = cmd.index("--allowedTools")
    allowed = cmd[idx + 1:]
    # Find next flag to bound the list
    end = len(allowed)
    for i, v in enumerate(allowed):
        if v.startswith("--"):
            end = i
            break
    allowed = allowed[:end]
    assert "Bash(python *)" in allowed


def test_builtin_tools_in_allowed_tools():
    """CLI must include spec.tools.builtin in --allowedTools."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd(
        "/usr/bin/claude", runtime, "homelab", _make_args(),
        system_prompt="You are homelab.",
    )
    idx = cmd.index("--allowedTools")
    allowed = cmd[idx + 1:]
    end = len(allowed)
    for i, v in enumerate(allowed):
        if v.startswith("--"):
            end = i
            break
    allowed = allowed[:end]
    assert "Bash" in allowed
    assert "Read" in allowed
