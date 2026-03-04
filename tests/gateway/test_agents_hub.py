"""Behavioral tests for AgentsHub — the coordinator wiring spec -> tools -> memory -> SDK.

NO mocks. Uses real AgentRegistry with YAML files on disk, real CapabilitiesRegistry,
real MemoryHub with SQLite backend, real EventEmitter.

Covers:
- build_agent returns AgentDefinition for valid agent
- build_agent raises ValueError for unknown/disabled agent
- build_all returns dict of all enabled agents, skips failures
- build_mcp_servers returns per-agent memory servers
- build_mcp_servers returns empty dict for disabled/unknown agents
- list_agents returns AgentSummary objects with correct fields
- create_agent persists and registers new agents
- update_agent patches agent description
- deactivate_agent disables an agent
- reload picks up new YAML files from disk
- AgentSummary dataclass round-trip
"""

from pathlib import Path

import pytest
import yaml

from corvus.agents.hub import AgentsHub, AgentSummary
from corvus.agents.registry import AgentRegistry
from corvus.agents.spec import AgentMemoryConfig, AgentSpec
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.model_router import ModelRouter
from tests.conftest import make_hub

# ---------------------------------------------------------------------------
# Helpers — real YAML on disk, real registries
# ---------------------------------------------------------------------------


def _write_spec(config_dir: Path, name: str, **overrides) -> None:
    """Write a real YAML agent spec to disk."""
    data = {
        "name": name,
        "description": f"{name} agent for testing",
        "enabled": True,
        "models": {"complexity": "medium"},
        "prompt_file": None,
        "tools": {
            "builtin": ["Bash"],
            "modules": {},
            "confirm_gated": [],
        },
        "memory": {
            "own_domain": name,
            "can_read_shared": True,
            "can_write": True,
        },
    }
    data.update(overrides)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / f"{name}.yaml").write_text(yaml.dump(data))


def _make_agents_hub(tmp_path: Path) -> AgentsHub:
    """Build a fully wired AgentsHub with 3 test agents on disk."""
    agents_dir = tmp_path / "config" / "agents"
    agents_dir.mkdir(parents=True)
    _write_spec(agents_dir, "personal")
    _write_spec(agents_dir, "work")
    _write_spec(agents_dir, "finance", models={"complexity": "high"})

    agent_registry = AgentRegistry(config_dir=agents_dir)
    agent_registry.load()

    capabilities = CapabilitiesRegistry()
    memory_hub = make_hub(tmp_path)
    model_router = ModelRouter(config={"defaults": {"model": "sonnet"}})
    emitter = EventEmitter()

    return AgentsHub(
        registry=agent_registry,
        capabilities=capabilities,
        memory_hub=memory_hub,
        model_router=model_router,
        emitter=emitter,
        config_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# Build tests
# ---------------------------------------------------------------------------


class TestAgentsHubBuild:
    """Test AgentsHub.build_agent and build_all."""

    def test_build_agent_returns_definition(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        defn = hub.build_agent("personal")
        assert defn.description is not None
        assert "personal" in defn.description.lower()

    def test_build_agent_has_prompt(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        defn = hub.build_agent("work")
        assert defn.prompt is not None
        assert len(defn.prompt) > 0

    def test_build_agent_includes_builtin_tools(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        defn = hub.build_agent("personal")
        assert "Bash" in defn.tools

    def test_build_agent_raises_for_unknown(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            hub.build_agent("nonexistent")

    def test_build_agent_raises_for_disabled(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        hub.deactivate_agent("work")
        with pytest.raises(ValueError, match="disabled"):
            hub.build_agent("work")

    def test_build_all_returns_all_enabled(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        result = hub.build_all()
        assert "personal" in result.agents
        assert "work" in result.agents
        assert "finance" in result.agents
        assert len(result.agents) == 3

    def test_build_all_skips_disabled_agents(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        hub.deactivate_agent("finance")
        result = hub.build_all()
        assert "personal" in result.agents
        assert "work" in result.agents
        assert "finance" not in result.agents
        assert len(result.agents) == 2


# ---------------------------------------------------------------------------
# Per-agent memory identity tests
# ---------------------------------------------------------------------------


class TestPerAgentMemoryIdentity:
    """The critical fix: each agent gets its own memory toolkit with correct identity."""

    def test_memory_servers_are_per_agent(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        personal_servers = hub.build_mcp_servers("personal")
        work_servers = hub.build_mcp_servers("work")
        assert "memory_personal" in personal_servers
        assert "memory_work" in work_servers

    def test_memory_server_names_differ(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        personal_servers = hub.build_mcp_servers("personal")
        work_servers = hub.build_mcp_servers("work")
        # The keys themselves are different — they're agent-scoped
        personal_keys = set(personal_servers.keys())
        work_keys = set(work_servers.keys())
        assert "memory_personal" in personal_keys
        assert "memory_personal" not in work_keys
        assert "memory_work" in work_keys
        assert "memory_work" not in personal_keys

    def test_disabled_agent_raises(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        hub.deactivate_agent("finance")
        with pytest.raises(ValueError, match="disabled"):
            hub.build_mcp_servers("finance")

    def test_unknown_agent_raises(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            hub.build_mcp_servers("nonexistent")


# ---------------------------------------------------------------------------
# Management tests
# ---------------------------------------------------------------------------


class TestAgentsHubManagement:
    """Test list, create, update, deactivate, reload operations."""

    def test_list_agents_returns_all(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        agents = hub.list_agents()
        assert len(agents) == 3
        names = {a.name for a in agents}
        assert names == {"personal", "work", "finance"}

    def test_list_agents_returns_summaries(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        agents = hub.list_agents()
        for agent in agents:
            assert isinstance(agent, AgentSummary)
            assert agent.description
            assert agent.complexity in {"high", "medium", "low"}

    def test_list_agents_finance_is_high_complexity(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        agents = hub.list_agents()
        finance = [a for a in agents if a.name == "finance"][0]
        assert finance.complexity == "high"

    def test_get_agent_returns_spec(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        spec = hub.get_agent("personal")
        assert spec is not None
        assert spec.name == "personal"

    def test_get_agent_returns_none_for_unknown(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        assert hub.get_agent("nonexistent") is None

    def test_create_agent(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        spec = AgentSpec(
            name="music",
            description="Music practice agent",
            memory=AgentMemoryConfig(own_domain="music"),
        )
        created = hub.create_agent(spec)
        assert created.name == "music"
        assert hub.get_agent("music") is not None
        assert hub.get_agent("music").description == "Music practice agent"

    def test_update_agent(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        updated = hub.update_agent("personal", {"description": "Updated personal agent"})
        assert updated.description == "Updated personal agent"
        # Verify persistence
        assert hub.get_agent("personal").description == "Updated personal agent"

    def test_deactivate_agent(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        hub.deactivate_agent("finance")
        spec = hub.get_agent("finance")
        assert spec is not None
        assert spec.enabled is False

    def test_reload_picks_up_new_spec(self, tmp_path):
        hub = _make_agents_hub(tmp_path)
        agents_dir = tmp_path / "config" / "agents"
        _write_spec(agents_dir, "music")
        result = hub.reload()
        assert "music" in result.added
        assert hub.get_agent("music") is not None


# ---------------------------------------------------------------------------
# AgentSummary dataclass tests
# ---------------------------------------------------------------------------


class TestAgentSummary:
    """Test the AgentSummary lightweight dataclass."""

    def test_summary_fields(self):
        summary = AgentSummary(
            name="test",
            description="Test agent",
            enabled=True,
            complexity="medium",
            tool_modules=["memory", "obsidian"],
            memory_domain="test",
            has_prompt=True,
        )
        assert summary.name == "test"
        assert summary.description == "Test agent"
        assert summary.enabled is True
        assert summary.complexity == "medium"
        assert summary.tool_modules == ["memory", "obsidian"]
        assert summary.memory_domain == "test"
        assert summary.has_prompt is True

    def test_summary_from_hub_list(self, tmp_path):
        """Summaries from list_agents() have all fields populated."""
        hub = _make_agents_hub(tmp_path)
        summaries = hub.list_agents()
        for s in summaries:
            assert isinstance(s.name, str) and len(s.name) > 0
            assert isinstance(s.description, str) and len(s.description) > 0
            assert isinstance(s.enabled, bool)
            assert isinstance(s.complexity, str)
            assert isinstance(s.tool_modules, list)
            assert isinstance(s.memory_domain, str)
            assert isinstance(s.has_prompt, bool)
