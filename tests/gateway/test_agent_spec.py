"""Behavioral tests for AgentSpec dataclasses.

NO mocks. Tests use real files on disk (tmp_path) and real YAML parsing.

Covers:
- Default values for all config dataclasses
- Full AgentSpec construction
- Prompt resolution (file exists, file missing, no prompt_file)
- to_dict / from_dict roundtrip serialization
- from_yaml loading from real YAML files
- Edge cases: empty tools, None memory, metadata passthrough
"""

import pytest
import yaml

from corvus.agents.spec import (
    AgentMemoryConfig,
    AgentModelConfig,
    AgentSpec,
    AgentToolConfig,
)

# ---------------------------------------------------------------------------
# 1. AgentModelConfig defaults
# ---------------------------------------------------------------------------


class TestAgentModelConfigDefaults:
    """AgentModelConfig should have sensible defaults when constructed bare."""

    def test_preferred_is_none(self):
        cfg = AgentModelConfig()
        assert cfg.preferred is None

    def test_fallback_is_none(self):
        cfg = AgentModelConfig()
        assert cfg.fallback is None

    def test_auto_is_true(self):
        cfg = AgentModelConfig()
        assert cfg.auto is True

    def test_complexity_default_medium(self):
        cfg = AgentModelConfig()
        assert cfg.complexity == "medium"

    def test_custom_values(self):
        cfg = AgentModelConfig(
            preferred="claude-opus-4-20250514",
            fallback="ollama/llama3",
            auto=False,
            complexity="high",
        )
        assert cfg.preferred == "claude-opus-4-20250514"
        assert cfg.fallback == "ollama/llama3"
        assert cfg.auto is False
        assert cfg.complexity == "high"


# ---------------------------------------------------------------------------
# 2. AgentToolConfig defaults
# ---------------------------------------------------------------------------


class TestAgentToolConfigDefaults:
    """AgentToolConfig should default to empty collections."""

    def test_builtin_empty_list(self):
        cfg = AgentToolConfig()
        assert cfg.builtin == []

    def test_modules_empty_dict(self):
        cfg = AgentToolConfig()
        assert cfg.modules == {}

    def test_confirm_gated_empty_list(self):
        cfg = AgentToolConfig()
        assert cfg.confirm_gated == []

    def test_custom_values(self):
        cfg = AgentToolConfig(
            builtin=["Bash", "Read"],
            modules={"paperless": {"url": "http://localhost:8000"}},
            confirm_gated=["mcp__paperless__paperless_bulk_edit"],
        )
        assert cfg.builtin == ["Bash", "Read"]
        assert "paperless" in cfg.modules
        assert cfg.confirm_gated == ["mcp__paperless__paperless_bulk_edit"]

    def test_mutable_defaults_are_independent(self):
        """Each instance must have its own lists/dicts (not shared references)."""
        a = AgentToolConfig()
        b = AgentToolConfig()
        a.builtin.append("Bash")
        assert b.builtin == [], "Mutable default should not be shared between instances"


# ---------------------------------------------------------------------------
# 3. AgentMemoryConfig
# ---------------------------------------------------------------------------


class TestAgentMemoryConfig:
    """AgentMemoryConfig has a required own_domain and optional fields."""

    def test_required_own_domain(self):
        cfg = AgentMemoryConfig(own_domain="homelab")
        assert cfg.own_domain == "homelab"

    def test_readable_domains_default_none(self):
        cfg = AgentMemoryConfig(own_domain="work")
        assert cfg.readable_domains is None

    def test_can_read_shared_default_true(self):
        cfg = AgentMemoryConfig(own_domain="finance")
        assert cfg.can_read_shared is True

    def test_can_write_default_true(self):
        cfg = AgentMemoryConfig(own_domain="personal")
        assert cfg.can_write is True

    def test_custom_values(self):
        cfg = AgentMemoryConfig(
            own_domain="docs",
            readable_domains=["finance", "work"],
            can_read_shared=False,
            can_write=False,
        )
        assert cfg.own_domain == "docs"
        assert cfg.readable_domains == ["finance", "work"]
        assert cfg.can_read_shared is False
        assert cfg.can_write is False


# ---------------------------------------------------------------------------
# 4. AgentSpec construction
# ---------------------------------------------------------------------------


class TestAgentSpecConstruction:
    """AgentSpec should be constructable with just name + description."""

    def test_minimal_construction(self):
        spec = AgentSpec(name="homelab", description="Manage homelab infrastructure")
        assert spec.name == "homelab"
        assert spec.description == "Manage homelab infrastructure"

    def test_enabled_default_true(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert spec.enabled is True

    def test_models_default(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert isinstance(spec.models, AgentModelConfig)
        assert spec.models.preferred is None

    def test_prompt_file_default_none(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert spec.prompt_file is None

    def test_tools_default(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert isinstance(spec.tools, AgentToolConfig)
        assert spec.tools.builtin == []

    def test_memory_default_none(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert spec.memory is None

    def test_metadata_default_empty_dict(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert spec.metadata == {}

    def test_full_construction(self):
        spec = AgentSpec(
            name="finance",
            description="Manage personal finances with Firefly III",
            enabled=True,
            models=AgentModelConfig(preferred="claude-opus-4-20250514", complexity="high"),
            prompt_file="prompts/finance.md",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"firefly": {"url": "http://localhost:8080"}},
                confirm_gated=["mcp__firefly__firefly_create_transaction"],
            ),
            memory=AgentMemoryConfig(own_domain="finance"),
            metadata={"version": "1.0"},
        )
        assert spec.name == "finance"
        assert spec.models.preferred == "claude-opus-4-20250514"
        assert spec.tools.modules["firefly"]["url"] == "http://localhost:8080"
        assert spec.memory.own_domain == "finance"
        assert spec.metadata["version"] == "1.0"


# ---------------------------------------------------------------------------
# 5. AgentSpec.prompt() resolution
# ---------------------------------------------------------------------------


class TestAgentSpecPrompt:
    """prompt() resolves prompt content from files relative to config_dir."""

    def test_prompt_from_file(self, tmp_path):
        """When prompt_file exists, return its content."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "homelab.md"
        prompt_file.write_text("You are the homelab agent. Manage Docker, Komodo, and NFS.")

        spec = AgentSpec(
            name="homelab",
            description="Homelab ops",
            prompt_file="prompts/homelab.md",
        )
        result = spec.prompt(tmp_path)
        assert result == "You are the homelab agent. Manage Docker, Komodo, and NFS."

    def test_prompt_missing_file_raises(self, tmp_path):
        """When prompt_file is set but file doesn't exist, raise FileNotFoundError."""
        spec = AgentSpec(
            name="homelab",
            description="Homelab ops",
            prompt_file="prompts/nonexistent.md",
        )
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            spec.prompt(tmp_path)

    def test_prompt_no_file_configured(self, tmp_path):
        """When prompt_file is None, return default prompt."""
        spec = AgentSpec(name="music", description="Music and piano")
        result = spec.prompt(tmp_path)
        assert "music" in result
        assert "You are the music agent" in result

    def test_prompt_default_format(self, tmp_path):
        """Default prompt includes agent name and task hint."""
        spec = AgentSpec(name="docs", description="Document management")
        result = spec.prompt(tmp_path)
        assert result == "You are the docs agent. Help the user with docs-related tasks."


# ---------------------------------------------------------------------------
# 6. AgentSpec.to_dict() serialization
# ---------------------------------------------------------------------------


class TestAgentSpecToDict:
    """to_dict() returns a plain dict suitable for YAML/JSON serialization."""

    def test_minimal_spec_to_dict(self):
        spec = AgentSpec(name="test", description="A test agent")
        d = spec.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "A test agent"
        assert d["enabled"] is True

    def test_nested_models_serialized(self):
        spec = AgentSpec(
            name="test",
            description="A test agent",
            models=AgentModelConfig(preferred="claude-opus-4-20250514"),
        )
        d = spec.to_dict()
        assert d["models"]["preferred"] == "claude-opus-4-20250514"
        assert d["models"]["auto"] is True

    def test_nested_tools_serialized(self):
        spec = AgentSpec(
            name="test",
            description="A test agent",
            tools=AgentToolConfig(builtin=["Bash", "Read"]),
        )
        d = spec.to_dict()
        assert d["tools"]["builtin"] == ["Bash", "Read"]

    def test_memory_serialized_when_present(self):
        spec = AgentSpec(
            name="test",
            description="A test agent",
            memory=AgentMemoryConfig(own_domain="work"),
        )
        d = spec.to_dict()
        assert d["memory"]["own_domain"] == "work"

    def test_memory_none_serialized(self):
        spec = AgentSpec(name="test", description="A test agent")
        d = spec.to_dict()
        assert d["memory"] is None

    def test_metadata_passthrough(self):
        spec = AgentSpec(name="test", description="A test agent", metadata={"key": "value"})
        d = spec.to_dict()
        assert d["metadata"] == {"key": "value"}


# ---------------------------------------------------------------------------
# 7. AgentSpec.from_dict() deserialization
# ---------------------------------------------------------------------------


class TestAgentSpecFromDict:
    """from_dict() reconstructs an AgentSpec from a plain dict."""

    def test_minimal_dict(self):
        data = {"name": "homelab", "description": "Homelab agent"}
        spec = AgentSpec.from_dict(data)
        assert spec.name == "homelab"
        assert spec.enabled is True
        assert isinstance(spec.models, AgentModelConfig)
        assert isinstance(spec.tools, AgentToolConfig)
        assert spec.memory is None

    def test_full_dict(self):
        data = {
            "name": "finance",
            "description": "Finance agent",
            "enabled": False,
            "models": {"preferred": "claude-opus-4-20250514", "complexity": "high"},
            "prompt_file": "prompts/finance.md",
            "tools": {
                "builtin": ["Bash"],
                "modules": {"firefly": {"url": "http://localhost:8080"}},
                "confirm_gated": ["mcp__firefly__create"],
            },
            "memory": {
                "own_domain": "finance",
                "readable_domains": ["work"],
                "can_read_shared": True,
                "can_write": True,
            },
            "metadata": {"author": "corvus"},
        }
        spec = AgentSpec.from_dict(data)
        assert spec.name == "finance"
        assert spec.enabled is False
        assert spec.models.preferred == "claude-opus-4-20250514"
        assert spec.models.complexity == "high"
        assert spec.prompt_file == "prompts/finance.md"
        assert spec.tools.builtin == ["Bash"]
        assert spec.tools.modules["firefly"]["url"] == "http://localhost:8080"
        assert spec.tools.confirm_gated == ["mcp__firefly__create"]
        assert spec.memory.own_domain == "finance"
        assert spec.memory.readable_domains == ["work"]
        assert spec.metadata["author"] == "corvus"

    def test_empty_models_dict(self):
        """Empty models dict should produce default AgentModelConfig."""
        data = {"name": "test", "description": "Test", "models": {}}
        spec = AgentSpec.from_dict(data)
        assert spec.models.preferred is None
        assert spec.models.auto is True

    def test_missing_memory_is_none(self):
        data = {"name": "test", "description": "Test"}
        spec = AgentSpec.from_dict(data)
        assert spec.memory is None


# ---------------------------------------------------------------------------
# 8. Roundtrip: to_dict -> from_dict
# ---------------------------------------------------------------------------


class TestAgentSpecRoundtrip:
    """to_dict() -> from_dict() must produce an equivalent spec."""

    def test_roundtrip_minimal(self):
        original = AgentSpec(name="test", description="Roundtrip test")
        data = original.to_dict()
        restored = AgentSpec.from_dict(data)
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.enabled == original.enabled
        assert restored.models.preferred == original.models.preferred
        assert restored.memory == original.memory

    def test_roundtrip_full(self):
        original = AgentSpec(
            name="homelab",
            description="Full homelab agent with everything configured",
            enabled=True,
            models=AgentModelConfig(
                preferred="claude-opus-4-20250514", fallback="ollama/llama3", auto=False, complexity="high"
            ),
            prompt_file="prompts/homelab.md",
            tools=AgentToolConfig(
                builtin=["Bash", "Read"],
                modules={"komodo": {"url": "http://localhost:9090"}},
                confirm_gated=["mcp__komodo__deploy"],
            ),
            memory=AgentMemoryConfig(
                own_domain="homelab",
                readable_domains=["work"],
                can_read_shared=True,
                can_write=True,
            ),
            metadata={"priority": 1, "tags": ["infra"]},
        )
        data = original.to_dict()
        restored = AgentSpec.from_dict(data)

        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.enabled == original.enabled
        assert restored.models.preferred == original.models.preferred
        assert restored.models.fallback == original.models.fallback
        assert restored.models.auto == original.models.auto
        assert restored.models.complexity == original.models.complexity
        assert restored.prompt_file == original.prompt_file
        assert restored.tools.builtin == original.tools.builtin
        assert restored.tools.modules == original.tools.modules
        assert restored.tools.confirm_gated == original.tools.confirm_gated
        assert restored.memory.own_domain == original.memory.own_domain
        assert restored.memory.readable_domains == original.memory.readable_domains
        assert restored.memory.can_read_shared == original.memory.can_read_shared
        assert restored.memory.can_write == original.memory.can_write
        assert restored.metadata == original.metadata


# ---------------------------------------------------------------------------
# 9. AgentSpec.from_yaml() — real YAML files
# ---------------------------------------------------------------------------


class TestAgentSpecFromYaml:
    """from_yaml() loads a spec from a real YAML file on disk."""

    def test_load_minimal_yaml(self, tmp_path):
        yaml_content = {
            "name": "personal",
            "description": "Personal assistant for day-to-day tasks",
        }
        yaml_file = tmp_path / "personal.yaml"
        with open(yaml_file, "w") as f:
            yaml.dump(yaml_content, f)

        spec = AgentSpec.from_yaml(yaml_file)
        assert spec.name == "personal"
        assert spec.description == "Personal assistant for day-to-day tasks"
        assert spec.enabled is True

    def test_load_full_yaml(self, tmp_path):
        yaml_content = {
            "name": "homelab",
            "description": "Manage homelab infrastructure",
            "enabled": True,
            "models": {
                "preferred": "claude-opus-4-20250514",
                "fallback": "ollama/llama3",
                "auto": False,
                "complexity": "high",
            },
            "prompt_file": "prompts/homelab.md",
            "tools": {
                "builtin": ["Bash", "Read"],
                "modules": {"komodo": {"url": "http://localhost:9090"}},
                "confirm_gated": ["mcp__komodo__deploy"],
            },
            "memory": {
                "own_domain": "homelab",
                "readable_domains": ["work"],
                "can_read_shared": True,
                "can_write": True,
            },
            "metadata": {"version": "2.0"},
        }
        yaml_file = tmp_path / "homelab.yaml"
        with open(yaml_file, "w") as f:
            yaml.dump(yaml_content, f)

        spec = AgentSpec.from_yaml(yaml_file)
        assert spec.name == "homelab"
        assert spec.models.preferred == "claude-opus-4-20250514"
        assert spec.models.fallback == "ollama/llama3"
        assert spec.tools.builtin == ["Bash", "Read"]
        assert spec.tools.modules["komodo"]["url"] == "http://localhost:9090"
        assert spec.memory.own_domain == "homelab"
        assert spec.metadata["version"] == "2.0"

    def test_yaml_roundtrip(self, tmp_path):
        """Write to_dict() to YAML, load via from_yaml(), compare."""
        original = AgentSpec(
            name="finance",
            description="Finance domain agent",
            models=AgentModelConfig(preferred="claude-opus-4-20250514"),
            tools=AgentToolConfig(builtin=["Bash"]),
            memory=AgentMemoryConfig(own_domain="finance", readable_domains=["work"]),
        )
        yaml_file = tmp_path / "finance.yaml"
        with open(yaml_file, "w") as f:
            yaml.dump(original.to_dict(), f)

        restored = AgentSpec.from_yaml(yaml_file)
        assert restored.name == original.name
        assert restored.models.preferred == original.models.preferred
        assert restored.tools.builtin == original.tools.builtin
        assert restored.memory.own_domain == original.memory.own_domain
        assert restored.memory.readable_domains == original.memory.readable_domains
