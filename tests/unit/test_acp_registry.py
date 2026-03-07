"""Behavioral tests for AcpAgentRegistry — real YAML on real filesystem."""

from pathlib import Path

import yaml

from corvus.acp.registry import AcpAgentRegistry

SAMPLE_AGENTS_CONFIG = {
    "agents": {
        "codex": {
            "command": "npx @zed-industries/codex-acp",
            "default_permissions": "approve-reads",
        },
        "gemini": {
            "command": "gemini",
            "default_permissions": "approve-reads",
        },
    }
}


def _write_config(config_dir: Path, data: dict) -> None:
    """Write a real YAML config file to the given directory."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "acp_agents.yaml"
    config_file.write_text(yaml.dump(data, default_flow_style=False))


def test_load_agents(tmp_path: Path) -> None:
    """Loading a valid config populates the registry with sorted agent names."""
    _write_config(tmp_path, SAMPLE_AGENTS_CONFIG)
    registry = AcpAgentRegistry(config_dir=tmp_path)
    registry.load()
    assert registry.list_agents() == ["codex", "gemini"]


def test_get_existing_agent(tmp_path: Path) -> None:
    """Getting an existing agent returns correct entry fields."""
    _write_config(tmp_path, SAMPLE_AGENTS_CONFIG)
    registry = AcpAgentRegistry(config_dir=tmp_path)
    registry.load()

    entry = registry.get("codex")
    assert entry is not None
    assert entry.name == "codex"
    assert entry.command == "npx @zed-industries/codex-acp"
    assert entry.default_permissions == "approve-reads"


def test_get_missing_agent(tmp_path: Path) -> None:
    """Getting a nonexistent agent returns None."""
    _write_config(tmp_path, SAMPLE_AGENTS_CONFIG)
    registry = AcpAgentRegistry(config_dir=tmp_path)
    registry.load()

    assert registry.get("nonexistent") is None


def test_load_missing_file(tmp_path: Path) -> None:
    """Loading from a directory without acp_agents.yaml warns but does not crash."""
    registry = AcpAgentRegistry(config_dir=tmp_path)
    registry.load()
    assert registry.list_agents() == []


def test_command_parts(tmp_path: Path) -> None:
    """command_parts() splits the command string into an argv list."""
    _write_config(tmp_path, SAMPLE_AGENTS_CONFIG)
    registry = AcpAgentRegistry(config_dir=tmp_path)
    registry.load()

    codex = registry.get("codex")
    assert codex is not None
    assert codex.command_parts() == ["npx", "@zed-industries/codex-acp"]

    gemini = registry.get("gemini")
    assert gemini is not None
    assert gemini.command_parts() == ["gemini"]
