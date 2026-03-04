"""Tests for RouterAgent integration with AgentRegistry.

Validates that:
1. RouterAgent reads agent names from registry when attached
2. RouterAgent falls back to VALID_AGENTS when no registry
3. parse_response uses dynamic agent set
4. _build_routing_prompt uses registry descriptions
"""

from pathlib import Path

import yaml

from corvus.agents.registry import AgentRegistry
from corvus.router import VALID_AGENTS, RouterAgent


def _seed_agents(config_dir: Path, names: list[str]) -> AgentRegistry:
    """Create agent YAML files and return a loaded registry."""
    config_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        data = {
            "name": name,
            "description": f"{name} agent for testing",
            "enabled": True,
            "models": {"complexity": "medium"},
            "memory": {"own_domain": name},
        }
        (config_dir / f"{name}.yaml").write_text(yaml.dump(data))
    reg = AgentRegistry(config_dir=config_dir)
    reg.load()
    return reg


class TestRouterAgentWithRegistry:
    """RouterAgent reads valid agents from AgentRegistry when attached."""

    def test_valid_agents_from_registry(self, tmp_path):
        reg = _seed_agents(tmp_path / "agents", ["personal", "work", "homelab"])
        ra = RouterAgent(registry=reg)
        valid = ra.get_valid_agents()
        assert valid == {"personal", "work", "homelab"}

    def test_valid_agents_fallback_without_registry(self):
        ra = RouterAgent()
        valid = ra.get_valid_agents()
        assert valid == VALID_AGENTS

    def test_parse_response_uses_registry_agents(self, tmp_path):
        reg = _seed_agents(tmp_path / "agents", ["alpha", "beta"])
        ra = RouterAgent(registry=reg)
        assert ra.parse_response("alpha") == "alpha"
        assert ra.parse_response("beta") == "beta"
        # "personal" is NOT in this registry, should fall back to general
        assert ra.parse_response("personal") == "general"

    def test_parse_response_without_registry_uses_hardcoded(self):
        ra = RouterAgent()
        assert ra.parse_response("personal") == "personal"
        assert ra.parse_response("homelab") == "homelab"
        assert ra.parse_response("unknown_agent") == "general"

    def test_registry_with_disabled_agent(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir(parents=True)
        # Create an enabled and a disabled agent
        for name, enabled in [("active", True), ("inactive", False)]:
            data = {
                "name": name,
                "description": f"{name} agent",
                "enabled": enabled,
                "memory": {"own_domain": name},
            }
            (agents_dir / f"{name}.yaml").write_text(yaml.dump(data))

        reg = AgentRegistry(config_dir=agents_dir)
        reg.load()
        ra = RouterAgent(registry=reg)

        valid = ra.get_valid_agents()
        assert "active" in valid
        assert "inactive" not in valid

    def test_routing_prompt_uses_registry_descriptions(self, tmp_path):
        reg = _seed_agents(tmp_path / "agents", ["myagent"])
        ra = RouterAgent(registry=reg)
        prompt = ra._build_routing_prompt()
        assert "myagent" in prompt
        assert "myagent agent for testing" in prompt

    def test_routing_prompt_fallback_without_registry(self):
        ra = RouterAgent()
        prompt = ra._build_routing_prompt()
        # Should be the static ROUTING_PROMPT
        assert "personal" in prompt
        assert "homelab" in prompt
