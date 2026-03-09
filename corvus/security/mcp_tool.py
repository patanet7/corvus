"""Base classes for MCP tool handlers with ToolContext injection.

MCPToolDef defines a tool with:
- name, description (minimal ~30 tokens for context window)
- input_schema (JSON Schema for typed inputs)
- requires_credentials (declared credential dependencies)
- is_mutation (whether this tool mutates state — for rate limiting)
- execute() — async handler receiving ToolContext + params
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from corvus.security.tool_context import ToolContext


@dataclass
class MCPToolDef:
    """Definition of an MCP tool with security metadata."""

    name: str
    description: str  # Keep minimal (~30 tokens) for context window
    input_schema: dict[str, Any] = field(default_factory=dict)
    requires_credentials: list[str] = field(default_factory=list)
    is_mutation: bool = False

    async def execute(self, ctx: ToolContext, **params: Any) -> str:
        """Execute the tool with the given context and parameters.

        Subclasses override this. Base implementation raises NotImplementedError.
        """
        raise NotImplementedError(f"Tool {self.name} has no execute implementation")


def resolve_credentials(
    tool_defs: list[MCPToolDef],
    credential_store: dict[str, str],
) -> dict[str, str]:
    """Resolve credentials for a set of tools from the credential store.

    Returns only the credentials that are declared as dependencies
    by the given tools. Tools that don't declare credentials get none.

    Raises KeyError if a required credential is missing from the store.
    """
    needed: set[str] = set()
    for tool_def in tool_defs:
        needed.update(tool_def.requires_credentials)

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key in sorted(needed):
        val = credential_store.get(key)
        if val is None:
            missing.append(key)
        else:
            resolved[key] = val

    if missing:
        raise KeyError(f"Missing required credentials: {', '.join(missing)}")

    return resolved
