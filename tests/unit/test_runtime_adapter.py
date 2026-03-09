"""Behavioral tests for RuntimeAdapter protocol and ClaudeCodeAdapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import runtime_checkable

from corvus.security.runtime_adapter import ClaudeCodeAdapter, RuntimeAdapter
from corvus.security.tool_context import PermissionTier


class TestClaudeCodeAdapterComposePermissions:
    """compose_permissions merges global_deny + extra_deny, deduplicates, and sorts."""

    def test_merges_global_and_extra_deny(self) -> None:
        adapter = ClaudeCodeAdapter()
        result = adapter.compose_permissions(
            tier=PermissionTier.DEFAULT,
            global_deny=["tool_a", "tool_b"],
            extra_deny=["tool_c"],
        )
        assert result == {"deny": ["tool_a", "tool_b", "tool_c"]}

    def test_deduplicates_deny_entries(self) -> None:
        adapter = ClaudeCodeAdapter()
        result = adapter.compose_permissions(
            tier=PermissionTier.DEFAULT,
            global_deny=["tool_a", "tool_b"],
            extra_deny=["tool_b", "tool_c"],
        )
        assert result == {"deny": ["tool_a", "tool_b", "tool_c"]}

    def test_sorts_deny_entries(self) -> None:
        adapter = ClaudeCodeAdapter()
        result = adapter.compose_permissions(
            tier=PermissionTier.STRICT,
            global_deny=["zebra", "alpha"],
            extra_deny=["mango"],
        )
        assert result["deny"] == ["alpha", "mango", "zebra"]

    def test_empty_lists_produce_empty_deny(self) -> None:
        adapter = ClaudeCodeAdapter()
        result = adapter.compose_permissions(
            tier=PermissionTier.DEFAULT,
            global_deny=[],
            extra_deny=[],
        )
        assert result == {"deny": []}


class TestClaudeCodeAdapterComposeSettings:
    """compose_settings produces valid JSON with required security fields."""

    def test_produces_valid_json(self) -> None:
        adapter = ClaudeCodeAdapter()
        raw = adapter.compose_settings(deny=["tool_x"])
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_includes_permissions_deny(self) -> None:
        adapter = ClaudeCodeAdapter()
        raw = adapter.compose_settings(deny=["tool_x", "tool_y"])
        parsed = json.loads(raw)
        assert parsed["permissions"]["deny"] == ["tool_x", "tool_y"]

    def test_includes_enabled_plugins_empty(self) -> None:
        adapter = ClaudeCodeAdapter()
        raw = adapter.compose_settings(deny=[])
        parsed = json.loads(raw)
        assert parsed["enabledPlugins"] == {}

    def test_includes_strict_known_marketplaces_empty(self) -> None:
        adapter = ClaudeCodeAdapter()
        raw = adapter.compose_settings(deny=[])
        parsed = json.loads(raw)
        assert parsed["strictKnownMarketplaces"] == []

    def test_has_exactly_three_top_level_keys(self) -> None:
        adapter = ClaudeCodeAdapter()
        raw = adapter.compose_settings(deny=["a"])
        parsed = json.loads(raw)
        assert set(parsed.keys()) == {
            "permissions",
            "enabledPlugins",
            "strictKnownMarketplaces",
        }


class TestClaudeCodeAdapterBuildLaunchCmd:
    """build_launch_cmd constructs Claude CLI command with correct flags."""

    def test_includes_system_prompt_flag(self) -> None:
        adapter = ClaudeCodeAdapter()
        cmd = adapter.build_launch_cmd(
            workspace=Path("/tmp/ws"),
            mcp_config={},
            system_prompt="You are a helper.",
            model=None,
        )
        idx = cmd.index("--system-prompt")
        assert cmd[idx + 1] == "You are a helper."

    def test_omits_model_flag_when_none(self) -> None:
        adapter = ClaudeCodeAdapter()
        cmd = adapter.build_launch_cmd(
            workspace=Path("/tmp/ws"),
            mcp_config={},
            system_prompt="test",
            model=None,
        )
        assert "--model" not in cmd

    def test_includes_model_flag_when_provided(self) -> None:
        adapter = ClaudeCodeAdapter()
        cmd = adapter.build_launch_cmd(
            workspace=Path("/tmp/ws"),
            mcp_config={},
            system_prompt="test",
            model="claude-sonnet-4-20250514",
        )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-20250514"

    def test_includes_setting_sources(self) -> None:
        adapter = ClaudeCodeAdapter()
        cmd = adapter.build_launch_cmd(
            workspace=Path("/tmp/ws"),
            mcp_config={},
            system_prompt="test",
            model=None,
        )
        idx = cmd.index("--setting-sources")
        assert cmd[idx + 1] == "user,project"

    def test_starts_with_claude_print_verbose(self) -> None:
        adapter = ClaudeCodeAdapter()
        cmd = adapter.build_launch_cmd(
            workspace=Path("/tmp/ws"),
            mcp_config={},
            system_prompt="test",
            model=None,
        )
        assert cmd[:3] == ["claude", "--print", "--verbose"]

    def test_omits_system_prompt_flag_when_empty(self) -> None:
        adapter = ClaudeCodeAdapter()
        cmd = adapter.build_launch_cmd(
            workspace=Path("/tmp/ws"),
            mcp_config={},
            system_prompt="",
            model=None,
        )
        assert "--system-prompt" not in cmd


class TestRuntimeAdapterProtocol:
    """ClaudeCodeAdapter structurally satisfies the RuntimeAdapter protocol."""

    def test_claude_code_adapter_is_runtime_adapter(self) -> None:
        # runtime_checkable Protocol allows isinstance checks
        assert isinstance(ClaudeCodeAdapter(), RuntimeAdapter)

    def test_adapter_has_compose_permissions_method(self) -> None:
        adapter = ClaudeCodeAdapter()
        assert callable(getattr(adapter, "compose_permissions", None))

    def test_adapter_has_compose_settings_method(self) -> None:
        adapter = ClaudeCodeAdapter()
        assert callable(getattr(adapter, "compose_settings", None))

    def test_adapter_has_build_launch_cmd_method(self) -> None:
        adapter = ClaudeCodeAdapter()
        assert callable(getattr(adapter, "build_launch_cmd", None))
