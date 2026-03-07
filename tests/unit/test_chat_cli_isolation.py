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
