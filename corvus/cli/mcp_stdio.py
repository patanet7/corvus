"""In-process MCP tool handler for agent tool execution.

Wraps MCPToolDef instances with permission checking, audit logging,
and ToolContext injection. The actual MCP protocol transport (stdio)
will be handled by claude-agent-sdk's create_sdk_mcp_server -- this
module provides the handler layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from corvus.security.mcp_tool import MCPToolDef
import structlog
from corvus.security.tool_context import ToolContext

logger = structlog.get_logger(__name__)


@dataclass
class ToolCallResult:
    """Result of a tool call."""

    tool_name: str
    success: bool
    result: str | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class MCPToolHandler:
    """Handles tool calls with permission checking and ToolContext injection.

    Wraps a set of MCPToolDef instances, validates permissions before
    execution, logs all calls (success and denial), and returns results.
    """

    tools: dict[str, MCPToolDef] = field(default_factory=dict)
    ctx: ToolContext | None = None

    @classmethod
    def from_tool_defs(
        cls,
        tool_defs: list[MCPToolDef],
        ctx: ToolContext,
    ) -> MCPToolHandler:
        """Create a handler from a list of tool definitions."""
        tools = {td.name: td for td in tool_defs}
        return cls(tools=tools, ctx=ctx)

    def list_tools(self) -> list[dict]:
        """Return tool definitions in MCP-compatible format.

        Each entry contains name, description, and inputSchema as
        required by the MCP tool listing protocol.
        """
        return [
            {
                "name": td.name,
                "description": td.description,
                "inputSchema": td.input_schema,
            }
            for td in self.tools.values()
        ]

    async def handle_tool_call(
        self,
        tool_name: str,
        params: dict,
    ) -> ToolCallResult:
        """Handle a tool call with full permission checking.

        Steps:
            1. Verify tool exists in registry
            2. Check deny list via ToolContext permissions
            3. Execute tool with ToolContext injection
            4. Return structured result with timing data
        """
        start = time.monotonic()

        # 1. Tool must be registered
        tool_def = self.tools.get(tool_name)
        if tool_def is None:
            logger.warning("tool_call_unknown", tool_name=tool_name)
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        # 2. Check deny list
        if self.ctx and self.ctx.permissions.is_denied(tool_name):
            logger.warning(
                "tool_call_denied",
                tool_name=tool_name,
                agent_name=self.ctx.agent_name,
            )
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' is denied by security policy.",
            )

        # 3. Execute with ToolContext
        try:
            result = await tool_def.execute(self.ctx, **params)
            duration = (time.monotonic() - start) * 1000
            logger.info(
                "tool_call_success",
                tool_name=tool_name,
                agent_name=self.ctx.agent_name if self.ctx else "unknown",
                duration_ms=round(duration, 1),
            )
            return ToolCallResult(
                tool_name=tool_name,
                success=True,
                result=result,
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.exception(
                "tool_call_failed",
                tool_name=tool_name,
                agent_name=self.ctx.agent_name if self.ctx else "unknown",
            )
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=str(exc),
                duration_ms=duration,
            )
