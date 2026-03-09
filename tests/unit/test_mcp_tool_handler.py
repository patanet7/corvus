"""Verify MCPToolDef base class and credential resolution."""

import asyncio

import pytest

from corvus.security.mcp_tool import MCPToolDef, resolve_credentials
from corvus.security.tool_context import PermissionTier, ToolContext, ToolPermissions


class TestMCPToolDef:
    def test_construction(self):
        tool = MCPToolDef(
            name="obsidian_search",
            description="Search notes",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            requires_credentials=["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
            is_mutation=False,
        )
        assert tool.name == "obsidian_search"
        assert tool.requires_credentials == ["OBSIDIAN_URL", "OBSIDIAN_API_KEY"]
        assert tool.is_mutation is False

    def test_base_execute_raises(self):
        tool = MCPToolDef(name="test", description="test")
        with pytest.raises(NotImplementedError, match="test"):
            asyncio.run(
                tool.execute(
                    ToolContext(
                        agent_name="test",
                        session_id="s1",
                        permission_tier=PermissionTier.DEFAULT,
                        credentials={},
                        permissions=ToolPermissions(),
                    )
                )
            )

    def test_defaults(self):
        tool = MCPToolDef(name="t", description="d")
        assert tool.input_schema == {}
        assert tool.requires_credentials == []
        assert tool.is_mutation is False


class TestResolveCredentials:
    def test_resolves_declared_deps(self):
        tools = [
            MCPToolDef(name="a", description="a", requires_credentials=["KEY_A"]),
            MCPToolDef(name="b", description="b", requires_credentials=["KEY_B"]),
        ]
        store = {"KEY_A": "val_a", "KEY_B": "val_b", "KEY_C": "val_c"}
        resolved = resolve_credentials(tools, store)
        assert resolved == {"KEY_A": "val_a", "KEY_B": "val_b"}
        assert "KEY_C" not in resolved  # Not declared, not resolved

    def test_missing_credential_raises(self):
        tools = [MCPToolDef(name="a", description="a", requires_credentials=["MISSING"])]
        with pytest.raises(KeyError, match="MISSING"):
            resolve_credentials(tools, {})

    def test_no_credentials_needed(self):
        tools = [MCPToolDef(name="a", description="a")]
        resolved = resolve_credentials(tools, {"KEY_A": "val"})
        assert resolved == {}

    def test_deduplicates_across_tools(self):
        tools = [
            MCPToolDef(name="a", description="a", requires_credentials=["SHARED"]),
            MCPToolDef(name="b", description="b", requires_credentials=["SHARED"]),
        ]
        store = {"SHARED": "val"}
        resolved = resolve_credentials(tools, store)
        assert resolved == {"SHARED": "val"}
