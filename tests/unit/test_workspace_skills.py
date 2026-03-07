"""Tests for per-agent skills copying into workspace."""

from pathlib import Path

import pytest

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
    """Agent with no skills/ dir -- nothing copied, no error."""
    config_dir = tmp_path / "config2"
    (config_dir / "config" / "agents" / "personal").mkdir(parents=True)
    copy_agent_skills("personal", config_dir, workspace)
    assert not (workspace / ".claude" / "skills").exists()


def test_shared_skills_copied(tmp_path: Path, workspace: Path) -> None:
    """Shared skills from config/skills/shared/ are copied if agent opts in."""
    config_dir = tmp_path / "project"
    shared_dir = config_dir / "config" / "skills" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "obsidian-vault.md").write_text("# Obsidian Vault\nHow to use vault.")

    agent_dir = config_dir / "config" / "agents" / "homelab"
    agent_dir.mkdir(parents=True)

    copy_agent_skills(
        agent_name="homelab",
        config_dir=config_dir,
        workspace_dir=workspace,
        shared_skills=["obsidian-vault"],
    )
    assert (workspace / ".claude" / "skills" / "obsidian-vault.md").exists()


def test_skill_content_preserved(agent_config_dir: Path, workspace: Path) -> None:
    """Copied skill has same content as original."""
    copy_agent_skills("homelab", agent_config_dir, workspace)
    original = (agent_config_dir / "config" / "agents" / "homelab" / "skills" / "docker-operations.md").read_text()
    copied = (workspace / ".claude" / "skills" / "docker-operations.md").read_text()
    assert original == copied
