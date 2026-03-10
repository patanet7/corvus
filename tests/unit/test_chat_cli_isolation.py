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

    def build_system_prompt(self, name):
        return f"You are {name}."


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
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    assert "--disable-slash-commands" not in cmd


def test_setting_sources_user_project():
    """CLI must pass --setting-sources user,project to load isolated settings."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    idx = cmd.index("--setting-sources")
    assert cmd[idx + 1] == "user,project"


def test_strict_mcp_config_present():
    """CLI must pass --strict-mcp-config to ignore global MCP configs."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    assert "--strict-mcp-config" in cmd


def test_uses_system_prompt():
    """CLI must use --system-prompt built from agents_hub."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    assert "--system-prompt" in cmd
    idx = cmd.index("--system-prompt")
    assert cmd[idx + 1] == "You are homelab."
    assert "--append-system-prompt" not in cmd


def test_no_mcp_config_when_no_path():
    """CLI must NOT pass --mcp-config when no mcp_config_path is given."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
    assert "--mcp-config" not in cmd


def test_builtin_tools_in_allowed_tools():
    """CLI must include spec.tools.builtin in --allowedTools."""
    runtime = _FakeRuntime()
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", _make_args())
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
