"""Tests for mcp_servers field on AgentToolConfig and AgentSpec."""

from corvus.agents.spec import AgentSpec, AgentToolConfig


class TestMcpServersField:
    def test_tool_config_defaults_to_empty_list(self) -> None:
        cfg = AgentToolConfig()
        assert cfg.mcp_servers == []

    def test_tool_config_accepts_mcp_servers(self) -> None:
        servers = [
            {"name": "komodo", "command": "npx", "args": ["-y", "@komodo/mcp"]},
        ]
        cfg = AgentToolConfig(mcp_servers=servers)
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers[0]["name"] == "komodo"

    def test_spec_from_dict_with_mcp_servers(self) -> None:
        data = {
            "name": "test",
            "description": "Test agent",
            "tools": {
                "builtin": ["Bash"],
                "modules": {},
                "confirm_gated": [],
                "mcp_servers": [
                    {
                        "name": "ext-server",
                        "command": "some-binary",
                        "args": ["--flag"],
                        "env": {"KEY": "val"},
                    }
                ],
            },
        }
        spec = AgentSpec.from_dict(data)
        assert len(spec.tools.mcp_servers) == 1
        assert spec.tools.mcp_servers[0]["name"] == "ext-server"

    def test_spec_from_dict_without_mcp_servers(self) -> None:
        data = {
            "name": "test",
            "description": "Test agent",
            "tools": {"builtin": ["Bash"], "modules": {}, "confirm_gated": []},
        }
        spec = AgentSpec.from_dict(data)
        assert spec.tools.mcp_servers == []

    def test_spec_to_dict_roundtrip(self) -> None:
        data = {
            "name": "test",
            "description": "Test agent",
            "tools": {
                "builtin": [],
                "modules": {},
                "confirm_gated": [],
                "mcp_servers": [{"name": "x", "command": "y", "args": []}],
            },
        }
        spec = AgentSpec.from_dict(data)
        out = spec.to_dict()
        assert out["tools"]["mcp_servers"] == [{"name": "x", "command": "y", "args": []}]
