"""Verify all agents loaded after directory migration."""

from pathlib import Path

import pytest

from corvus.agents.registry import AgentRegistry


EXPECTED_AGENTS = [
    "docs",
    "email",
    "finance",
    "general",
    "home",
    "homelab",
    "huginn",
    "music",
    "personal",
    "work",
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


def test_agents_have_prompt_and_soul(real_registry: AgentRegistry) -> None:
    """After migration, agents with prompt/soul files should have them set."""
    for spec in real_registry.list_all():
        assert spec.prompt_file is not None, f"{spec.name} missing prompt_file"
        assert spec.soul_file is not None, f"{spec.name} missing soul_file"


def test_prompt_files_resolve(real_registry: AgentRegistry) -> None:
    """All prompt_file paths should point to real files on disk."""
    for spec in real_registry.list_all():
        if spec.prompt_file:
            path = Path(spec.prompt_file)
            assert path.exists(), f"{spec.name} prompt_file {spec.prompt_file} does not exist"


def test_soul_files_resolve(real_registry: AgentRegistry) -> None:
    """All soul_file paths should point to real files on disk."""
    for spec in real_registry.list_all():
        if spec.soul_file:
            path = Path(spec.soul_file)
            assert path.exists(), f"{spec.name} soul_file {spec.soul_file} does not exist"
