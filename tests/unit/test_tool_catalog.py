"""Behavioral tests for corvus.security.tool_catalog.

Validates that the tool catalog returns correct MCPToolDef instances
for each module, respects config flags, and declares accurate
credential dependencies.
"""

from corvus.security.mcp_tool import MCPToolDef
from corvus.security.tool_catalog import get_module_tool_defs


# ---------------------------------------------------------------------------
# Obsidian module
# ---------------------------------------------------------------------------


class TestObsidianTools:
    def test_read_only_returns_search_and_read(self) -> None:
        tools = get_module_tool_defs("obsidian", {"read": True, "write": False})
        names = [t.name for t in tools]
        assert "obsidian_search" in names
        assert "obsidian_read" in names
        assert "obsidian_write" not in names
        assert "obsidian_append" not in names

    def test_write_enabled_returns_write_tools(self) -> None:
        tools = get_module_tool_defs("obsidian", {"read": True, "write": True})
        names = [t.name for t in tools]
        assert "obsidian_search" in names
        assert "obsidian_read" in names
        assert "obsidian_write" in names
        assert "obsidian_append" in names

    def test_write_tools_are_mutations(self) -> None:
        tools = get_module_tool_defs("obsidian", {"read": True, "write": True})
        by_name = {t.name: t for t in tools}
        assert by_name["obsidian_write"].is_mutation is True
        assert by_name["obsidian_append"].is_mutation is True
        assert by_name["obsidian_search"].is_mutation is False
        assert by_name["obsidian_read"].is_mutation is False

    def test_all_obsidian_tools_require_obsidian_credentials(self) -> None:
        tools = get_module_tool_defs("obsidian", {"read": True, "write": True})
        for tool in tools:
            assert "OBSIDIAN_URL" in tool.requires_credentials
            assert "OBSIDIAN_API_KEY" in tool.requires_credentials

    def test_default_config_returns_read_tools(self) -> None:
        """Default config (read=True implicit) returns read tools."""
        tools = get_module_tool_defs("obsidian", {})
        names = [t.name for t in tools]
        assert "obsidian_search" in names
        assert "obsidian_read" in names
        assert "obsidian_write" not in names

    def test_all_are_mcp_tool_def_instances(self) -> None:
        tools = get_module_tool_defs("obsidian", {"read": True, "write": True})
        for tool in tools:
            assert isinstance(tool, MCPToolDef)


# ---------------------------------------------------------------------------
# Home Assistant module
# ---------------------------------------------------------------------------


class TestHaTools:
    def test_returns_all_three_tools(self) -> None:
        tools = get_module_tool_defs("ha", {})
        names = [t.name for t in tools]
        assert "ha_list_entities" in names
        assert "ha_get_state" in names
        assert "ha_call_service" in names

    def test_call_service_is_mutation(self) -> None:
        tools = get_module_tool_defs("ha", {})
        by_name = {t.name: t for t in tools}
        assert by_name["ha_call_service"].is_mutation is True
        assert by_name["ha_list_entities"].is_mutation is False
        assert by_name["ha_get_state"].is_mutation is False

    def test_all_ha_tools_require_ha_credentials(self) -> None:
        tools = get_module_tool_defs("ha", {})
        for tool in tools:
            assert "HA_URL" in tool.requires_credentials
            assert "HA_TOKEN" in tool.requires_credentials

    def test_call_service_schema_requires_domain_and_service(self) -> None:
        tools = get_module_tool_defs("ha", {})
        by_name = {t.name: t for t in tools}
        schema = by_name["ha_call_service"].input_schema
        assert "domain" in schema["required"]
        assert "service" in schema["required"]


# ---------------------------------------------------------------------------
# Paperless module
# ---------------------------------------------------------------------------


class TestPaperlessTools:
    def test_returns_all_five_tools(self) -> None:
        tools = get_module_tool_defs("paperless", {})
        names = [t.name for t in tools]
        assert "paperless_search" in names
        assert "paperless_read" in names
        assert "paperless_tags" in names
        assert "paperless_tag" in names
        assert "paperless_bulk_edit" in names

    def test_mutation_flags(self) -> None:
        tools = get_module_tool_defs("paperless", {})
        by_name = {t.name: t for t in tools}
        assert by_name["paperless_search"].is_mutation is False
        assert by_name["paperless_read"].is_mutation is False
        assert by_name["paperless_tags"].is_mutation is False
        assert by_name["paperless_tag"].is_mutation is True
        assert by_name["paperless_bulk_edit"].is_mutation is True

    def test_all_paperless_tools_require_paperless_credentials(self) -> None:
        tools = get_module_tool_defs("paperless", {})
        for tool in tools:
            assert "PAPERLESS_URL" in tool.requires_credentials
            assert "PAPERLESS_API_TOKEN" in tool.requires_credentials


# ---------------------------------------------------------------------------
# Firefly module
# ---------------------------------------------------------------------------


class TestFireflyTools:
    def test_returns_all_five_tools(self) -> None:
        tools = get_module_tool_defs("firefly", {})
        names = [t.name for t in tools]
        assert "firefly_transactions" in names
        assert "firefly_accounts" in names
        assert "firefly_categories" in names
        assert "firefly_summary" in names
        assert "firefly_create_transaction" in names

    def test_create_transaction_is_mutation(self) -> None:
        tools = get_module_tool_defs("firefly", {})
        by_name = {t.name: t for t in tools}
        assert by_name["firefly_create_transaction"].is_mutation is True
        assert by_name["firefly_transactions"].is_mutation is False
        assert by_name["firefly_accounts"].is_mutation is False

    def test_all_firefly_tools_require_firefly_credentials(self) -> None:
        tools = get_module_tool_defs("firefly", {})
        for tool in tools:
            assert "FIREFLY_URL" in tool.requires_credentials
            assert "FIREFLY_API_TOKEN" in tool.requires_credentials

    def test_create_transaction_schema_requires_description_and_amount(self) -> None:
        tools = get_module_tool_defs("firefly", {})
        by_name = {t.name: t for t in tools}
        schema = by_name["firefly_create_transaction"].input_schema
        assert "description" in schema["required"]
        assert "amount" in schema["required"]


# ---------------------------------------------------------------------------
# Email module
# ---------------------------------------------------------------------------


class TestEmailTools:
    def test_default_returns_all_tools(self) -> None:
        tools = get_module_tool_defs("email", {})
        names = [t.name for t in tools]
        assert "email_list" in names
        assert "email_read" in names
        assert "email_draft" in names
        assert "email_send" in names
        assert "email_archive" in names
        assert "email_label" in names
        assert "email_labels" in names

    def test_read_only_returns_only_read_tools(self) -> None:
        tools = get_module_tool_defs("email", {"read_only": True})
        names = [t.name for t in tools]
        assert "email_list" in names
        assert "email_read" in names
        assert "email_draft" not in names
        assert "email_send" not in names
        assert "email_archive" not in names

    def test_write_tools_are_mutations(self) -> None:
        tools = get_module_tool_defs("email", {})
        by_name = {t.name: t for t in tools}
        assert by_name["email_list"].is_mutation is False
        assert by_name["email_read"].is_mutation is False
        assert by_name["email_draft"].is_mutation is True
        assert by_name["email_send"].is_mutation is True
        assert by_name["email_archive"].is_mutation is True

    def test_email_tools_require_no_env_credentials(self) -> None:
        """Email uses OAuth tokens, not env var credentials."""
        tools = get_module_tool_defs("email", {})
        for tool in tools:
            assert tool.requires_credentials == []


# ---------------------------------------------------------------------------
# Drive module
# ---------------------------------------------------------------------------


class TestDriveTools:
    def test_default_returns_all_tools(self) -> None:
        tools = get_module_tool_defs("drive", {})
        names = [t.name for t in tools]
        assert "drive_list" in names
        assert "drive_read" in names
        assert "drive_create" in names
        assert "drive_edit" in names
        assert "drive_move" in names
        assert "drive_delete" in names
        assert "drive_permanent_delete" in names
        assert "drive_share" in names
        assert "drive_cleanup" in names

    def test_read_only_returns_only_read_tools(self) -> None:
        tools = get_module_tool_defs("drive", {"read_only": True})
        names = [t.name for t in tools]
        assert "drive_list" in names
        assert "drive_read" in names
        assert "drive_create" not in names
        assert "drive_delete" not in names

    def test_write_tools_are_mutations(self) -> None:
        tools = get_module_tool_defs("drive", {})
        by_name = {t.name: t for t in tools}
        assert by_name["drive_list"].is_mutation is False
        assert by_name["drive_read"].is_mutation is False
        assert by_name["drive_create"].is_mutation is True
        assert by_name["drive_delete"].is_mutation is True
        assert by_name["drive_permanent_delete"].is_mutation is True
        assert by_name["drive_share"].is_mutation is True

    def test_drive_tools_require_no_env_credentials(self) -> None:
        """Drive uses OAuth tokens, not env var credentials."""
        tools = get_module_tool_defs("drive", {})
        for tool in tools:
            assert tool.requires_credentials == []


# ---------------------------------------------------------------------------
# Memory module
# ---------------------------------------------------------------------------


class TestMemoryTools:
    def test_returns_all_five_tools(self) -> None:
        tools = get_module_tool_defs("memory", {})
        names = [t.name for t in tools]
        assert "memory_search" in names
        assert "memory_save" in names
        assert "memory_get" in names
        assert "memory_list" in names
        assert "memory_forget" in names

    def test_memory_tools_require_no_credentials(self) -> None:
        """Memory tools use the local MemoryHub, no external credentials."""
        tools = get_module_tool_defs("memory", {})
        for tool in tools:
            assert tool.requires_credentials == []

    def test_mutation_flags(self) -> None:
        tools = get_module_tool_defs("memory", {})
        by_name = {t.name: t for t in tools}
        assert by_name["memory_search"].is_mutation is False
        assert by_name["memory_save"].is_mutation is True
        assert by_name["memory_get"].is_mutation is False
        assert by_name["memory_list"].is_mutation is False
        assert by_name["memory_forget"].is_mutation is True

    def test_all_are_mcp_tool_def_instances(self) -> None:
        tools = get_module_tool_defs("memory", {})
        for tool in tools:
            assert isinstance(tool, MCPToolDef)

    def test_memory_save_schema_requires_content(self) -> None:
        tools = get_module_tool_defs("memory", {})
        by_name = {t.name: t for t in tools}
        schema = by_name["memory_save"].input_schema
        assert "content" in schema["required"]


# ---------------------------------------------------------------------------
# Cross-module tests
# ---------------------------------------------------------------------------


class TestCrossModule:
    def test_unknown_module_returns_empty(self) -> None:
        tools = get_module_tool_defs("nonexistent_module", {})
        assert tools == []

    def test_all_tools_have_input_schemas(self) -> None:
        """Every tool in every module must have an input_schema with type=object."""
        for module in ["obsidian", "ha", "paperless", "firefly", "email", "drive", "memory"]:
            tools = get_module_tool_defs(module, {"read": True, "write": True})
            for tool in tools:
                assert tool.input_schema.get("type") == "object", (
                    f"{tool.name} missing type=object in input_schema"
                )

    def test_all_tools_have_descriptions(self) -> None:
        """Every tool must have a non-empty description."""
        for module in ["obsidian", "ha", "paperless", "firefly", "email", "drive", "memory"]:
            tools = get_module_tool_defs(module, {"read": True, "write": True})
            for tool in tools:
                assert tool.description, f"{tool.name} has empty description"

    def test_credential_env_var_patterns(self) -> None:
        """All credential declarations should follow UPPER_SNAKE_CASE pattern."""
        import re

        pattern = re.compile(r"^[A-Z][A-Z0-9_]+$")
        for module in ["obsidian", "ha", "paperless", "firefly", "email", "drive", "memory"]:
            tools = get_module_tool_defs(module, {"read": True, "write": True})
            for tool in tools:
                for cred in tool.requires_credentials:
                    assert pattern.match(cred), (
                        f"{tool.name} has non-standard credential name: {cred}"
                    )

    def test_tool_names_match_registry_convention(self) -> None:
        """Tool names should use module_action format (underscores, no dots)."""
        for module in ["obsidian", "ha", "paperless", "firefly", "email", "drive", "memory"]:
            tools = get_module_tool_defs(module, {"read": True, "write": True})
            for tool in tools:
                assert "_" in tool.name, f"{tool.name} should use underscore format"
                assert "." not in tool.name, f"{tool.name} should not contain dots"

    def test_all_returned_are_mcp_tool_def(self) -> None:
        """Every returned tool must be an MCPToolDef instance."""
        for module in ["obsidian", "ha", "paperless", "firefly", "email", "drive", "memory"]:
            tools = get_module_tool_defs(module, {"read": True, "write": True})
            for tool in tools:
                assert isinstance(tool, MCPToolDef), (
                    f"{tool.name} is {type(tool).__name__}, not MCPToolDef"
                )
