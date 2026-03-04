"""Tests for tool module registration functions.

Validates that TOOL_MODULE_DEFS correctly registers all 6 tool modules
with proper names, env gates, per-agent flags, and lifecycle callables.
"""

from corvus.capabilities.modules import TOOL_MODULE_DEFS


class TestToolModuleDefs:
    def test_all_modules_defined(self):
        names = {d.name for d in TOOL_MODULE_DEFS}
        assert names == {"obsidian", "email", "drive", "ha", "paperless", "firefly"}

    def test_obsidian_is_per_agent(self):
        obs = next(d for d in TOOL_MODULE_DEFS if d.name == "obsidian")
        assert obs.supports_per_agent is True

    def test_shared_modules_not_per_agent(self):
        for d in TOOL_MODULE_DEFS:
            if d.name != "obsidian":
                assert not d.supports_per_agent, f"{d.name} should not be per-agent"

    def test_all_modules_have_env_gates(self):
        for d in TOOL_MODULE_DEFS:
            assert len(d.requires_env) > 0, f"{d.name} should have env gate"

    def test_all_modules_have_configure(self):
        for d in TOOL_MODULE_DEFS:
            assert d.configure is not None, f"{d.name} should have configure"

    def test_all_modules_have_create_tools(self):
        for d in TOOL_MODULE_DEFS:
            assert d.create_tools is not None, f"{d.name} should have create_tools"

    def test_all_modules_have_create_mcp_server(self):
        for d in TOOL_MODULE_DEFS:
            assert d.create_mcp_server is not None, f"{d.name} should have create_mcp_server"

    def test_env_gate_values(self):
        """Verify specific env var requirements for each module."""
        by_name = {d.name: d for d in TOOL_MODULE_DEFS}
        assert "OBSIDIAN_API_KEY" in by_name["obsidian"].requires_env
        assert "GOOGLE_CREDS_PATH" in by_name["email"].requires_env
        assert "GOOGLE_CREDS_PATH" in by_name["drive"].requires_env
        assert "HA_URL" in by_name["ha"].requires_env
        assert "PAPERLESS_URL" in by_name["paperless"].requires_env
        assert "FIREFLY_URL" in by_name["firefly"].requires_env

    def test_ha_requires_token(self):
        """HA also needs HA_TOKEN."""
        by_name = {d.name: d for d in TOOL_MODULE_DEFS}
        assert "HA_TOKEN" in by_name["ha"].requires_env

    def test_paperless_requires_token(self):
        """Paperless also needs PAPERLESS_API_TOKEN."""
        by_name = {d.name: d for d in TOOL_MODULE_DEFS}
        assert "PAPERLESS_API_TOKEN" in by_name["paperless"].requires_env

    def test_firefly_requires_token(self):
        """Firefly also needs FIREFLY_API_TOKEN."""
        by_name = {d.name: d for d in TOOL_MODULE_DEFS}
        assert "FIREFLY_API_TOKEN" in by_name["firefly"].requires_env

    def test_obsidian_requires_url(self):
        """Obsidian also needs OBSIDIAN_URL."""
        by_name = {d.name: d for d in TOOL_MODULE_DEFS}
        assert "OBSIDIAN_URL" in by_name["obsidian"].requires_env

    def test_callables_are_callable(self):
        """Verify all lifecycle callables are actually callable."""
        for d in TOOL_MODULE_DEFS:
            assert callable(d.configure), f"{d.name}.configure not callable"
            assert callable(d.create_tools), f"{d.name}.create_tools not callable"
            assert callable(d.create_mcp_server), f"{d.name}.create_mcp_server not callable"

    def test_module_count(self):
        """Exactly 6 modules should be registered."""
        assert len(TOOL_MODULE_DEFS) == 6

    def test_no_duplicate_names(self):
        """Module names must be unique."""
        names = [d.name for d in TOOL_MODULE_DEFS]
        assert len(names) == len(set(names)), f"Duplicate names found: {names}"

    def test_entries_are_tool_module_entry_instances(self):
        """Each entry should be a ToolModuleEntry."""
        from corvus.capabilities.registry import ToolModuleEntry

        for d in TOOL_MODULE_DEFS:
            assert isinstance(d, ToolModuleEntry), f"{d.name} is not a ToolModuleEntry"
