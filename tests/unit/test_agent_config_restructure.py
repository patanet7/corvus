"""Tests for directory-based agent config loading."""

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
    (base / "soul.md").write_text("You are a sysadmin who loves containers.")
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
    (base / "personal.yaml").write_text(
        yaml.dump({"name": "personal", "description": "Personal", "models": {"complexity": "medium"}})
    )
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
