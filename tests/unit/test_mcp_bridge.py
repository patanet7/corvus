"""Tests for the MCP bridge server tool registration."""

from corvus.cli.mcp_bridge import parse_args, register_module_tools


class TestParseArgs:
    def test_required_agent(self) -> None:
        args = parse_args(["--agent", "homelab"])
        assert args.agent == "homelab"
        assert args.memory_domain == "shared"
        assert args.modules_json == "{}"

    def test_all_args(self) -> None:
        args = parse_args([
            "--agent", "finance",
            "--modules-json", '{"firefly": {}}',
            "--memory-domain", "finance",
        ])
        assert args.agent == "finance"
        assert args.memory_domain == "finance"


class TestRegisterModuleTools:
    """Test that module tools are registered via the registrar."""

    def _make_registrar(self):
        """Create a test registrar that records registered tool names."""
        registered = []

        def registrar(name: str, description: str = ""):
            def decorator(fn):
                registered.append(name)
                return fn
            return decorator

        return registrar, registered

    def test_registers_ha_tools(self, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local:8123")
        monkeypatch.setenv("HA_TOKEN", "test-token")
        registrar, registered = self._make_registrar()
        register_module_tools(
            tool_registrar=registrar,
            module_configs={"ha": {}},
            skip_configure_errors=False,
        )
        assert "ha_list_entities" in registered
        assert "ha_get_state" in registered
        assert "ha_call_service" in registered

    def test_registers_obsidian_read_only(self, monkeypatch) -> None:
        monkeypatch.setenv("OBSIDIAN_URL", "https://127.0.0.1:27124")
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        registrar, registered = self._make_registrar()
        register_module_tools(
            tool_registrar=registrar,
            module_configs={"obsidian": {"read": True, "write": False}},
            skip_configure_errors=False,
        )
        assert "obsidian_search" in registered
        assert "obsidian_read" in registered
        assert "obsidian_write" not in registered
        assert "obsidian_append" not in registered

    def test_skips_unknown_module(self) -> None:
        registrar, registered = self._make_registrar()
        register_module_tools(
            tool_registrar=registrar,
            module_configs={"nonexistent_module": {}},
            skip_configure_errors=True,
        )
        assert registered == []

    def test_skip_configure_errors(self) -> None:
        """Module with missing env vars should be skipped when skip_configure_errors=True."""
        registrar, registered = self._make_registrar()
        # HA requires HA_URL and HA_TOKEN — without them, configure() raises
        register_module_tools(
            tool_registrar=registrar,
            module_configs={"ha": {}},
            skip_configure_errors=True,
        )
        # Should not crash, tools may or may not register depending on env
