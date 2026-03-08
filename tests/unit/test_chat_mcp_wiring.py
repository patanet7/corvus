"""Tests for MCP config wiring in corvus chat CLI.

Verifies that _build_agent_mcp_config generates the correct config file
and that _build_claude_cmd includes/excludes --mcp-config appropriately.

No mocks -- uses real CapabilitiesRegistry, AgentSpec, and file I/O.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from corvus.agents.spec import AgentMemoryConfig, AgentSpec, AgentToolConfig
from corvus.capabilities.registry import CapabilitiesRegistry, ToolModuleEntry
from corvus.cli.chat import _build_agent_mcp_config

# ---------------------------------------------------------------------------
# Helpers: lightweight stand-in objects that satisfy the attribute contracts
# _build_agent_mcp_config reads from runtime.  NO mocks -- these are plain
# dataclasses with real behaviour.
# ---------------------------------------------------------------------------


class _SimpleAgentsHub:
    """Minimal agents hub backed by a dict of specs."""

    def __init__(self, specs: dict[str, AgentSpec] | None = None) -> None:
        self._specs: dict[str, AgentSpec] = specs or {}

    def get_agent(self, name: str) -> AgentSpec | None:
        return self._specs.get(name)


@dataclass
class _MinimalRuntime:
    """Holds only the attributes _build_agent_mcp_config reads."""

    capabilities_registry: CapabilitiesRegistry = field(default_factory=CapabilitiesRegistry)
    agents_hub: _SimpleAgentsHub = field(default_factory=_SimpleAgentsHub)


# ---------------------------------------------------------------------------
# Tests for _build_agent_mcp_config
# ---------------------------------------------------------------------------


class TestBuildAgentMcpConfig:
    """Tests for per-agent MCP config generation."""

    def test_generates_config_file_with_bridge_entry(self, tmp_path: Path) -> None:
        """Config file is created containing corvus-tools bridge server."""
        caps = CapabilitiesRegistry()
        caps.register(
            "ha",
            ToolModuleEntry(
                name="ha",
                configure=lambda cfg: cfg,
                create_tools=lambda cfg: [],
                create_mcp_server=lambda tools, cfg: None,
                requires_env=["HA_URL", "HA_TOKEN"],
            ),
        )

        spec = AgentSpec(
            name="homelab",
            description="Homelab agent",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"ha": {"some_key": "some_val"}},
                mcp_servers=[],
            ),
            memory=AgentMemoryConfig(own_domain="homelab"),
        )

        runtime = _MinimalRuntime(
            capabilities_registry=caps,
            agents_hub=_SimpleAgentsHub({"homelab": spec}),
        )

        config_path = _build_agent_mcp_config("homelab", runtime, tmp_path)

        assert config_path is not None
        assert config_path.exists()
        assert config_path.name == ".corvus-mcp.json"

        data = json.loads(config_path.read_text())
        assert "mcpServers" in data
        assert "corvus-tools" in data["mcpServers"]

        bridge = data["mcpServers"]["corvus-tools"]
        assert bridge["command"] == "uv"
        assert "--agent" in bridge["args"]
        assert "homelab" in bridge["args"]
        assert "--memory-domain" in bridge["args"]
        assert "homelab" in bridge["args"]

    def test_includes_module_configs_in_bridge_args(self, tmp_path: Path) -> None:
        """Bridge server args contain modules-json with module configs."""
        caps = CapabilitiesRegistry()
        caps.register(
            "paperless",
            ToolModuleEntry(
                name="paperless",
                configure=lambda cfg: cfg,
                create_tools=lambda cfg: [],
                create_mcp_server=lambda tools, cfg: None,
                requires_env=["PAPERLESS_URL"],
            ),
        )

        spec = AgentSpec(
            name="docs",
            description="Documents agent",
            tools=AgentToolConfig(
                modules={"paperless": {"base_url": "http://localhost:8000"}},
            ),
            memory=AgentMemoryConfig(own_domain="docs"),
        )

        runtime = _MinimalRuntime(
            capabilities_registry=caps,
            agents_hub=_SimpleAgentsHub({"docs": spec}),
        )

        config_path = _build_agent_mcp_config("docs", runtime, tmp_path)
        assert config_path is not None

        data = json.loads(config_path.read_text())
        bridge_args = data["mcpServers"]["corvus-tools"]["args"]
        modules_idx = bridge_args.index("--modules-json")
        modules_json = json.loads(bridge_args[modules_idx + 1])
        assert "paperless" in modules_json
        assert modules_json["paperless"]["base_url"] == "http://localhost:8000"

    def test_includes_external_mcp_servers(self, tmp_path: Path) -> None:
        """External MCP servers from agent spec are merged into config."""
        spec = AgentSpec(
            name="work",
            description="Work agent",
            tools=AgentToolConfig(
                modules={},
                mcp_servers=[
                    {
                        "name": "github-mcp",
                        "command": "npx",
                        "args": ["-y", "@github/mcp-server"],
                        "env": {},
                    }
                ],
            ),
            memory=AgentMemoryConfig(own_domain="work"),
        )

        runtime = _MinimalRuntime(
            agents_hub=_SimpleAgentsHub({"work": spec}),
        )

        config_path = _build_agent_mcp_config("work", runtime, tmp_path)
        assert config_path is not None

        data = json.loads(config_path.read_text())
        assert "github-mcp" in data["mcpServers"]
        assert data["mcpServers"]["github-mcp"]["command"] == "npx"

    def test_returns_none_for_missing_agent(self, tmp_path: Path) -> None:
        """Returns None when agent is not found in the hub."""
        runtime = _MinimalRuntime(
            agents_hub=_SimpleAgentsHub({}),
        )

        result = _build_agent_mcp_config("nonexistent", runtime, tmp_path)
        assert result is None

    def test_uses_shared_domain_when_no_memory_config(self, tmp_path: Path) -> None:
        """Falls back to 'shared' memory domain when agent has no memory config."""
        spec = AgentSpec(
            name="personal",
            description="Personal agent",
            tools=AgentToolConfig(modules={}),
            memory=None,
        )

        runtime = _MinimalRuntime(
            agents_hub=_SimpleAgentsHub({"personal": spec}),
        )

        config_path = _build_agent_mcp_config("personal", runtime, tmp_path)
        assert config_path is not None

        data = json.loads(config_path.read_text())
        bridge_args = data["mcpServers"]["corvus-tools"]["args"]
        domain_idx = bridge_args.index("--memory-domain")
        assert bridge_args[domain_idx + 1] == "shared"

    def test_config_file_has_restricted_permissions(self, tmp_path: Path) -> None:
        """Config file is written with 0600 permissions (owner read/write only)."""
        spec = AgentSpec(
            name="finance",
            description="Finance agent",
            tools=AgentToolConfig(modules={}),
            memory=AgentMemoryConfig(own_domain="finance"),
        )

        runtime = _MinimalRuntime(
            agents_hub=_SimpleAgentsHub({"finance": spec}),
        )

        config_path = _build_agent_mcp_config("finance", runtime, tmp_path)
        assert config_path is not None
        assert oct(config_path.stat().st_mode & 0o777) == oct(0o600)

    def test_handles_agent_with_empty_modules(self, tmp_path: Path) -> None:
        """Agent with empty modules dict still generates a valid config."""
        spec = AgentSpec(
            name="music",
            description="Music agent",
            tools=AgentToolConfig(builtin=["Bash"], modules={}),
            memory=AgentMemoryConfig(own_domain="music"),
        )

        runtime = _MinimalRuntime(
            agents_hub=_SimpleAgentsHub({"music": spec}),
        )

        config_path = _build_agent_mcp_config("music", runtime, tmp_path)
        assert config_path is not None

        data = json.loads(config_path.read_text())
        assert "corvus-tools" in data["mcpServers"]

    def test_unregistered_module_skipped_in_requires_env(self, tmp_path: Path) -> None:
        """Module not in capabilities registry gets empty requires_env list."""
        # Agent requests "custom_mod" but it's not registered in capabilities
        spec = AgentSpec(
            name="test",
            description="Test agent",
            tools=AgentToolConfig(modules={"custom_mod": {"key": "val"}}),
            memory=AgentMemoryConfig(own_domain="test"),
        )

        runtime = _MinimalRuntime(
            agents_hub=_SimpleAgentsHub({"test": spec}),
        )

        # Should not raise -- unregistered module just has no env requirements
        config_path = _build_agent_mcp_config("test", runtime, tmp_path)
        assert config_path is not None

        data = json.loads(config_path.read_text())
        bridge = data["mcpServers"]["corvus-tools"]
        # The bridge env should be empty since module isn't registered
        assert bridge["env"] == {}


class _SimpleModelRouter:
    """Minimal model router satisfying resolve_backend_and_model requirements."""

    def get_model(self, name: str) -> str:
        return "claude-sonnet-4-20250514"

    def get_backend(self, name: str) -> str:
        return "claude"


class _CmdAgentsHub(_SimpleAgentsHub):
    """Agents hub that also provides build_system_prompt for _build_claude_cmd."""

    def build_system_prompt(self, name: str) -> str:
        return f"You are {name}."


@dataclass
class _CmdRuntime:
    """Runtime with all attributes _build_claude_cmd reads."""

    capabilities_registry: CapabilitiesRegistry = field(default_factory=CapabilitiesRegistry)
    agents_hub: _CmdAgentsHub = field(default_factory=_CmdAgentsHub)
    model_router: _SimpleModelRouter = field(default_factory=_SimpleModelRouter)


class TestBuildClaudeCmdMcpConfig:
    """Test that _build_claude_cmd handles mcp_config_path correctly.

    Uses a minimal runtime stub to call the real function.
    """

    def _make_runtime(self) -> _CmdRuntime:
        spec = AgentSpec(
            name="test",
            description="Test agent",
            tools=AgentToolConfig(builtin=["Bash"]),
            memory=AgentMemoryConfig(own_domain="test"),
        )
        return _CmdRuntime(
            agents_hub=_CmdAgentsHub({"test": spec}),
        )

    def test_mcp_config_flag_present_when_path_given(self, tmp_path: Path) -> None:
        """--mcp-config appears in command when a config path is provided."""
        from corvus.cli.chat import _build_claude_cmd, parse_args

        runtime = self._make_runtime()
        args = parse_args(["--agent", "test"])
        config_path = tmp_path / ".corvus-mcp.json"
        config_path.write_text("{}")

        cmd = _build_claude_cmd(
            "/usr/bin/claude",
            runtime,
            "test",
            args,
            mcp_config_path=config_path,
        )
        assert "--mcp-config" in cmd
        assert str(config_path) in cmd

    def test_mcp_config_flag_absent_when_path_is_none(self) -> None:
        """--mcp-config does NOT appear when config path is None."""
        from corvus.cli.chat import _build_claude_cmd, parse_args

        runtime = self._make_runtime()
        args = parse_args(["--agent", "test"])

        cmd = _build_claude_cmd(
            "/usr/bin/claude",
            runtime,
            "test",
            args,
            mcp_config_path=None,
        )
        assert "--mcp-config" not in cmd
