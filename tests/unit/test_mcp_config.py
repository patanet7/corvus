"""Tests for MCP config generation for CLI agents."""

import json
import os
from pathlib import Path

import pytest

from corvus.cli.mcp_config import build_mcp_config, resolve_bridge_env


class TestResolveBridgeEnv:
    """Test env var cherry-picking for the bridge server."""

    def test_picks_only_required_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local")
        monkeypatch.setenv("HA_TOKEN", "secret-token")
        monkeypatch.setenv("UNRELATED", "should-not-appear")
        result = resolve_bridge_env(requires_env=["HA_URL", "HA_TOKEN"])
        assert result == {"HA_URL": "http://ha.local", "HA_TOKEN": "secret-token"}
        assert "UNRELATED" not in result

    def test_skips_missing_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local")
        monkeypatch.delenv("HA_TOKEN", raising=False)
        result = resolve_bridge_env(requires_env=["HA_URL", "HA_TOKEN"])
        assert result == {"HA_URL": "http://ha.local"}

    def test_empty_requires(self) -> None:
        result = resolve_bridge_env(requires_env=[])
        assert result == {}


class TestBuildMcpConfig:
    """Test full MCP config JSON generation."""

    def test_generates_bridge_entry(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local")
        monkeypatch.setenv("HA_TOKEN", "tok")
        config_path = build_mcp_config(
            agent_name="homelab",
            module_configs={"ha": {}},
            requires_env_by_module={"ha": ["HA_URL", "HA_TOKEN"]},
            external_mcp_servers=[],
            output_dir=tmp_path,
            memory_domain="homelab",
        )
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "mcpServers" in data
        assert "corvus-tools" in data["mcpServers"]
        bridge = data["mcpServers"]["corvus-tools"]
        assert bridge["command"] == "uv"
        assert "--agent" in bridge["args"]
        assert "homelab" in bridge["args"]
        assert bridge["env"]["HA_URL"] == "http://ha.local"
        assert bridge["env"]["HA_TOKEN"] == "tok"

    def test_includes_external_servers(self, tmp_path: Path) -> None:
        externals = [
            {
                "name": "komodo-mcp",
                "command": "npx",
                "args": ["-y", "@komodo/mcp"],
                "env": {"KEY": "val"},
            }
        ]
        config_path = build_mcp_config(
            agent_name="homelab",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=externals,
            output_dir=tmp_path,
            memory_domain="homelab",
        )
        data = json.loads(config_path.read_text())
        assert "komodo-mcp" in data["mcpServers"]
        ext = data["mcpServers"]["komodo-mcp"]
        assert ext["command"] == "npx"
        assert ext["env"]["KEY"] == "val"

    def test_resolves_env_vars_in_external(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "resolved-val")
        externals = [
            {"name": "ext", "command": "bin", "args": [], "env": {"TOK": "${MY_TOKEN}"}},
        ]
        config_path = build_mcp_config(
            agent_name="test",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=externals,
            output_dir=tmp_path,
            memory_domain="shared",
        )
        data = json.loads(config_path.read_text())
        assert data["mcpServers"]["ext"]["env"]["TOK"] == "resolved-val"

    def test_http_transport_external(self, tmp_path: Path) -> None:
        externals = [
            {"name": "loki", "transport": "http", "url": "http://localhost:3100/mcp"},
        ]
        config_path = build_mcp_config(
            agent_name="homelab",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=externals,
            output_dir=tmp_path,
            memory_domain="homelab",
        )
        data = json.loads(config_path.read_text())
        assert "loki" in data["mcpServers"]
        loki = data["mcpServers"]["loki"]
        assert loki["url"] == "http://localhost:3100/mcp"
        assert loki.get("type") == "http"

    def test_file_permissions(self, tmp_path: Path) -> None:
        config_path = build_mcp_config(
            agent_name="test",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=[],
            output_dir=tmp_path,
            memory_domain="shared",
        )
        stat = config_path.stat()
        assert oct(stat.st_mode & 0o777) == "0o600"

    def test_bridge_always_present_for_memory(self, tmp_path: Path) -> None:
        config_path = build_mcp_config(
            agent_name="test",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=[],
            output_dir=tmp_path,
            memory_domain="shared",
        )
        data = json.loads(config_path.read_text())
        assert "corvus-tools" in data["mcpServers"]
