"""Smoke tests for corvus chat CLI integration."""

import json
import subprocess
import sys
from pathlib import Path


def test_chat_help_exits_zero() -> None:
    """corvus chat --help exits 0 and shows usage."""
    result = subprocess.run(
        [sys.executable, "-m", "corvus.cli.chat", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Launch Claude Code CLI" in result.stdout


def test_chat_module_imports() -> None:
    """Chat modules import without error."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("from corvus.cli.chat import parse_args; from corvus.cli.chat_render import render_welcome"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"


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


def test_mcp_config_generated_for_agent(tmp_path: Path) -> None:
    """Verify MCP config is generated with correct shape for a real agent."""
    from corvus.cli.mcp_config import build_mcp_config

    config_path = build_mcp_config(
        agent_name="homelab",
        module_configs={"ha": {}, "obsidian": {"read": True, "write": False}},
        requires_env_by_module={
            "ha": ["HA_URL", "HA_TOKEN"],
            "obsidian": ["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
        },
        external_mcp_servers=[],
        output_dir=tmp_path,
        memory_domain="homelab",
    )
    data = json.loads(config_path.read_text())

    # Bridge server entry exists
    assert "corvus-tools" in data["mcpServers"]
    bridge = data["mcpServers"]["corvus-tools"]
    assert bridge["command"] == "uv"
    assert "--agent" in bridge["args"]
    assert "homelab" in bridge["args"]

    # Modules JSON is in the args
    modules_idx = bridge["args"].index("--modules-json") + 1
    modules = json.loads(bridge["args"][modules_idx])
    assert "ha" in modules
    assert "obsidian" in modules
    assert modules["obsidian"]["read"] is True

    # Memory domain is in the args
    domain_idx = bridge["args"].index("--memory-domain") + 1
    assert bridge["args"][domain_idx] == "homelab"


def test_bridge_parse_args() -> None:
    """Verify bridge server CLI arg parsing."""
    from corvus.cli.mcp_bridge import parse_args

    args = parse_args(["--agent", "finance", "--modules-json", '{"firefly": {}}', "--memory-domain", "finance"])
    assert args.agent == "finance"
    assert args.memory_domain == "finance"
    modules = json.loads(args.modules_json)
    assert "firefly" in modules
