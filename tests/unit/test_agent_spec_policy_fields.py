"""Behavioral tests for AgentToolConfig permission_tier and extra_deny fields."""

import tempfile
from pathlib import Path

import pytest
import yaml

from corvus.agents.spec import AgentSpec, AgentToolConfig


class TestPermissionTierDefaults:
    def test_default_permission_tier_is_default(self):
        config = AgentToolConfig()
        assert config.permission_tier == "default"

    def test_strict_tier_accepted(self):
        config = AgentToolConfig(permission_tier="strict")
        assert config.permission_tier == "strict"

    def test_break_glass_tier_accepted(self):
        config = AgentToolConfig(permission_tier="break_glass")
        assert config.permission_tier == "break_glass"

    def test_invalid_tier_raises_value_error(self):
        with pytest.raises(ValueError, match="permission_tier must be one of"):
            AgentToolConfig(permission_tier="admin")

    def test_empty_string_tier_raises_value_error(self):
        with pytest.raises(ValueError, match="permission_tier must be one of"):
            AgentToolConfig(permission_tier="")


class TestExtraDenyDefaults:
    def test_extra_deny_defaults_to_empty_list(self):
        config = AgentToolConfig()
        assert config.extra_deny == []

    def test_extra_deny_can_be_set(self):
        patterns = ["Bash(rm *)", "Write(/etc/*)"]
        config = AgentToolConfig(extra_deny=patterns)
        assert config.extra_deny == patterns

    def test_extra_deny_instances_are_independent(self):
        a = AgentToolConfig()
        b = AgentToolConfig()
        a.extra_deny.append("something")
        assert b.extra_deny == []


class TestFromDictRoundTrip:
    def test_from_dict_with_new_fields(self):
        data = {
            "name": "test-agent",
            "description": "A test agent",
            "tools": {
                "builtin": ["Read"],
                "permission_tier": "strict",
                "extra_deny": ["Bash(rm *)"],
            },
            "memory": {"own_domain": "test"},
        }
        spec = AgentSpec.from_dict(data)
        assert spec.tools.permission_tier == "strict"
        assert spec.tools.extra_deny == ["Bash(rm *)"]

    def test_from_dict_without_new_fields_uses_defaults(self):
        data = {
            "name": "test-agent",
            "description": "A test agent",
            "tools": {"builtin": ["Read"]},
            "memory": {"own_domain": "test"},
        }
        spec = AgentSpec.from_dict(data)
        assert spec.tools.permission_tier == "default"
        assert spec.tools.extra_deny == []

    def test_to_dict_includes_new_fields(self):
        spec = AgentSpec.from_dict(
            {
                "name": "test-agent",
                "description": "A test agent",
                "tools": {
                    "permission_tier": "break_glass",
                    "extra_deny": ["Write(/secrets/*)"],
                },
                "memory": {"own_domain": "test"},
            }
        )
        d = spec.to_dict()
        assert d["tools"]["permission_tier"] == "break_glass"
        assert d["tools"]["extra_deny"] == ["Write(/secrets/*)"]

    def test_round_trip_preserves_new_fields(self):
        original = {
            "name": "roundtrip",
            "description": "Round-trip test",
            "tools": {
                "builtin": ["Read", "Glob"],
                "permission_tier": "strict",
                "extra_deny": ["Bash(curl *)", "Write(/etc/*)"],
            },
            "memory": {"own_domain": "roundtrip"},
        }
        spec = AgentSpec.from_dict(original)
        restored = AgentSpec.from_dict(spec.to_dict())
        assert restored.tools.permission_tier == "strict"
        assert restored.tools.extra_deny == ["Bash(curl *)", "Write(/etc/*)"]


class TestYamlRoundTrip:
    def test_yaml_with_new_fields(self):
        yaml_content = {
            "name": "yaml-agent",
            "description": "YAML round-trip test",
            "tools": {
                "builtin": ["Read"],
                "permission_tier": "strict",
                "extra_deny": ["Bash(rm -rf *)"],
            },
            "memory": {"own_domain": "yaml"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_content, f)
            f.flush()
            spec = AgentSpec.from_yaml(Path(f.name))
        assert spec.tools.permission_tier == "strict"
        assert spec.tools.extra_deny == ["Bash(rm -rf *)"]

    def test_yaml_without_new_fields_uses_defaults(self):
        yaml_content = {
            "name": "legacy-agent",
            "description": "No new fields",
            "tools": {"builtin": ["Read"]},
            "memory": {"own_domain": "legacy"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_content, f)
            f.flush()
            spec = AgentSpec.from_yaml(Path(f.name))
        assert spec.tools.permission_tier == "default"
        assert spec.tools.extra_deny == []


class TestBackwardCompatibilityWithRealYAMLs:
    """Ensure all existing agent YAMLs in config/ still load without errors."""

    CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "agents"

    def test_all_existing_agent_yamls_load(self):
        loaded = []
        # Flat layout
        for yaml_file in sorted(self.CONFIG_DIR.glob("*.yaml")):
            spec = AgentSpec.from_yaml(yaml_file)
            assert spec.tools.permission_tier == "default"
            assert spec.tools.extra_deny == []
            loaded.append(spec.name)
        # Directory layout
        for subdir in sorted(self.CONFIG_DIR.iterdir()):
            agent_yaml = subdir / "agent.yaml"
            if subdir.is_dir() and agent_yaml.exists():
                spec = AgentSpec.from_yaml(agent_yaml)
                assert spec.tools.permission_tier == "default"
                assert spec.tools.extra_deny == []
                loaded.append(spec.name)
        assert len(loaded) > 0, "No agent YAMLs found — test is vacuous"
