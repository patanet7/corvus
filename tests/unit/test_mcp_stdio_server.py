"""Behavioral tests for MCPToolHandler — in-process MCP tool handler.

Tests use real MCPToolDef subclasses that do actual work (echo, fail,
compute). No mocks, no monkeypatch, no fakes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from corvus.cli.mcp_stdio import MCPToolHandler, ToolCallResult
from corvus.security.mcp_tool import MCPToolDef
from corvus.security.tool_context import PermissionTier, ToolContext, ToolPermissions


# ---------------------------------------------------------------------------
# Real tool implementations for testing
# ---------------------------------------------------------------------------


class EchoTool(MCPToolDef):
    """Simple test tool that echoes input."""

    def __init__(self) -> None:
        super().__init__(
            name="echo",
            description="Echo input back",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )

    async def execute(self, ctx: ToolContext | None, **params: Any) -> str:
        return f"echo: {params.get('message', '')}"


class FailTool(MCPToolDef):
    """Tool that always raises an error."""

    def __init__(self) -> None:
        super().__init__(
            name="fail",
            description="Always fails",
            input_schema={"type": "object", "properties": {}},
        )

    async def execute(self, ctx: ToolContext | None, **params: Any) -> str:
        raise RuntimeError("intentional failure")


class AddTool(MCPToolDef):
    """Tool that adds two numbers — verifies real computation."""

    def __init__(self) -> None:
        super().__init__(
            name="add",
            description="Add two numbers",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
        )

    async def execute(self, ctx: ToolContext | None, **params: Any) -> str:
        return str(int(params["a"]) + int(params["b"]))


class SlowTool(MCPToolDef):
    """Tool with a small delay — for verifying duration tracking."""

    def __init__(self) -> None:
        super().__init__(
            name="slow",
            description="Sleeps briefly",
            input_schema={"type": "object", "properties": {}},
        )

    async def execute(self, ctx: ToolContext | None, **params: Any) -> str:
        await asyncio.sleep(0.01)
        return "done"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    agent_name: str = "test-agent",
    deny: list[str] | None = None,
) -> ToolContext:
    """Create a real ToolContext with optional deny list."""
    return ToolContext(
        agent_name=agent_name,
        session_id="sess-001",
        permission_tier=PermissionTier.DEFAULT,
        credentials={},
        permissions=ToolPermissions(deny=deny or []),
    )


def _make_handler(
    tools: list[MCPToolDef] | None = None,
    deny: list[str] | None = None,
) -> MCPToolHandler:
    """Build a handler with given tools and deny list."""
    if tools is None:
        tools = [EchoTool(), FailTool(), AddTool(), SlowTool()]
    ctx = _make_ctx(deny=deny)
    return MCPToolHandler.from_tool_defs(tools, ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFromToolDefs:
    """Tests for MCPToolHandler.from_tool_defs construction."""

    def test_constructs_with_all_tools(self) -> None:
        handler = _make_handler()
        assert len(handler.tools) == 4
        assert "echo" in handler.tools
        assert "fail" in handler.tools
        assert "add" in handler.tools
        assert "slow" in handler.tools

    def test_ctx_is_set(self) -> None:
        handler = _make_handler()
        assert handler.ctx is not None
        assert handler.ctx.agent_name == "test-agent"

    def test_empty_tool_list(self) -> None:
        handler = _make_handler(tools=[])
        assert handler.tools == {}

    def test_duplicate_names_last_wins(self) -> None:
        """If two tools share a name, the last one wins (dict semantics)."""
        tool_a = EchoTool()
        tool_b = EchoTool()
        tool_b.description = "second echo"
        handler = _make_handler(tools=[tool_a, tool_b])
        assert len(handler.tools) == 1
        assert handler.tools["echo"].description == "second echo"


class TestListTools:
    """Tests for MCP-compatible tool listing."""

    def test_returns_mcp_format(self) -> None:
        handler = _make_handler(tools=[EchoTool()])
        result = handler.list_tools()
        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "echo"
        assert entry["description"] == "Echo input back"
        assert "inputSchema" in entry
        assert entry["inputSchema"]["type"] == "object"

    def test_all_tools_listed(self) -> None:
        handler = _make_handler()
        result = handler.list_tools()
        names = {t["name"] for t in result}
        assert names == {"echo", "fail", "add", "slow"}

    def test_empty_handler_returns_empty_list(self) -> None:
        handler = _make_handler(tools=[])
        assert handler.list_tools() == []


class TestHandleToolCall:
    """Tests for handle_tool_call execution path."""

    @pytest.mark.asyncio
    async def test_successful_call(self) -> None:
        handler = _make_handler()
        result = await handler.handle_tool_call("echo", {"message": "hello"})
        assert result.success is True
        assert result.result == "echo: hello"
        assert result.tool_name == "echo"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_unknown_tool(self) -> None:
        handler = _make_handler()
        result = await handler.handle_tool_call("nonexistent", {})
        assert result.success is False
        assert "Unknown tool" in result.error
        assert result.tool_name == "nonexistent"

    @pytest.mark.asyncio
    async def test_denied_tool(self) -> None:
        handler = _make_handler(deny=["echo"])
        result = await handler.handle_tool_call("echo", {"message": "blocked"})
        assert result.success is False
        assert "denied by security policy" in result.error
        assert result.tool_name == "echo"

    @pytest.mark.asyncio
    async def test_denied_tool_glob_pattern(self) -> None:
        """Deny patterns support fnmatch globs."""
        handler = _make_handler(deny=["echo*"])
        result = await handler.handle_tool_call("echo", {"message": "blocked"})
        assert result.success is False
        assert "denied" in result.error

    @pytest.mark.asyncio
    async def test_failing_tool_returns_error(self) -> None:
        handler = _make_handler()
        result = await handler.handle_tool_call("fail", {})
        assert result.success is False
        assert result.error == "intentional failure"
        assert result.tool_name == "fail"

    @pytest.mark.asyncio
    async def test_add_tool_computes(self) -> None:
        handler = _make_handler()
        result = await handler.handle_tool_call("add", {"a": 3, "b": 7})
        assert result.success is True
        assert result.result == "10"

    @pytest.mark.asyncio
    async def test_duration_ms_populated(self) -> None:
        handler = _make_handler()
        result = await handler.handle_tool_call("slow", {})
        assert result.success is True
        assert result.duration_ms > 0.0
        # Should be at least ~10ms due to the sleep
        assert result.duration_ms >= 5.0

    @pytest.mark.asyncio
    async def test_duration_on_failure(self) -> None:
        handler = _make_handler()
        result = await handler.handle_tool_call("fail", {})
        assert result.success is False
        assert result.duration_ms >= 0.0

    @pytest.mark.asyncio
    async def test_non_denied_tool_still_works_with_deny_list(self) -> None:
        """A deny list for one tool should not affect other tools."""
        handler = _make_handler(deny=["fail"])
        result = await handler.handle_tool_call("echo", {"message": "allowed"})
        assert result.success is True
        assert result.result == "echo: allowed"


class TestToolCallResult:
    """Tests for ToolCallResult data class."""

    def test_defaults(self) -> None:
        r = ToolCallResult(tool_name="t", success=True)
        assert r.result is None
        assert r.error is None
        assert r.duration_ms == 0.0

    def test_all_fields(self) -> None:
        r = ToolCallResult(
            tool_name="t",
            success=False,
            result=None,
            error="oops",
            duration_ms=42.5,
        )
        assert r.tool_name == "t"
        assert r.success is False
        assert r.error == "oops"
        assert r.duration_ms == 42.5
