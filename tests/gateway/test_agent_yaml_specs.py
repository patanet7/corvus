"""Validate all default agent YAML specs load correctly."""

from pathlib import Path

import pytest

from corvus.agents.spec import AgentSpec

CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "agents"
EXPECTED_AGENTS = {"personal", "work", "homelab", "finance", "email", "docs", "music", "home", "general", "huginn"}


class TestDefaultAgentSpecs:
    @pytest.fixture(scope="class")
    def specs(self) -> dict[str, AgentSpec]:
        result = {}
        # Flat layout: config/agents/*.yaml
        for yaml_file in sorted(CONFIG_DIR.glob("*.yaml")):
            spec = AgentSpec.from_yaml(yaml_file)
            result[spec.name] = spec
        # Directory layout: config/agents/*/agent.yaml (with prompt.md, soul.md convention)
        for subdir in sorted(CONFIG_DIR.iterdir()):
            agent_yaml = subdir / "agent.yaml"
            if subdir.is_dir() and agent_yaml.exists():
                spec = AgentSpec.from_yaml(agent_yaml)
                prompt_path = subdir / "prompt.md"
                soul_path = subdir / "soul.md"
                if prompt_path.exists() and not spec.prompt_file:
                    spec.prompt_file = str(prompt_path.relative_to(CONFIG_DIR.parent.parent))
                if soul_path.exists() and not spec.soul_file:
                    spec.soul_file = str(soul_path.relative_to(CONFIG_DIR.parent.parent))
                result[spec.name] = spec
        return result

    def test_all_expected_agents_exist(self, specs):
        assert set(specs.keys()) == EXPECTED_AGENTS

    def test_all_agents_enabled(self, specs):
        for name, spec in specs.items():
            assert spec.enabled, f"{name} should be enabled"

    def test_all_agents_have_description(self, specs):
        for name, spec in specs.items():
            assert spec.description, f"{name} missing description"

    def test_all_agents_have_memory_domain(self, specs):
        for name, spec in specs.items():
            assert spec.memory is not None, f"{name} missing memory config"
            assert spec.memory.own_domain, f"{name} missing own_domain"

    def test_all_agents_have_prompt_file(self, specs):
        for name, spec in specs.items():
            assert spec.prompt_file is not None, f"{name} missing prompt_file"

    def test_prompt_files_exist(self, specs):
        project_root = Path(__file__).parent.parent.parent
        for name, spec in specs.items():
            prompt_path = project_root / spec.prompt_file
            assert prompt_path.exists(), f"{name}: prompt file {spec.prompt_file} does not exist"

    def test_complexity_values_valid(self, specs):
        valid = {"high", "medium", "low"}
        for _name, spec in specs.items():
            assert spec.models.complexity in valid

    def test_memory_domains_unique(self, specs):
        domains = [s.memory.own_domain for s in specs.values()]
        non_shared = [d for d in domains if d != "shared"]
        assert len(non_shared) == len(set(non_shared))

    def test_obsidian_write_agents_have_confirm_gating(self, specs):
        for name, spec in specs.items():
            obs = spec.tools.modules.get("obsidian")
            if obs and obs.get("write"):
                assert "obsidian.write" in spec.tools.confirm_gated or "obsidian.append" in spec.tools.confirm_gated, (
                    f"{name}: obsidian write without confirm-gating"
                )
