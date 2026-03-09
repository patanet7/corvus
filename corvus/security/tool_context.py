"""ToolContext — runtime security context passed to every tool handler."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum


class PermissionTier(str, Enum):
    """Permission tier for agent tool access."""

    STRICT = "strict"
    DEFAULT = "default"
    BREAK_GLASS = "break_glass"


@dataclass
class ToolPermissions:
    """Resolved deny/confirm sets for an agent session."""

    deny: list[str] = field(default_factory=list)
    confirm_gated: list[str] = field(default_factory=list)

    def is_denied(self, tool_name: str) -> bool:
        """Check if tool_name matches any deny pattern (fnmatch glob)."""
        return any(fnmatch.fnmatch(tool_name, pattern) for pattern in self.deny)

    def is_confirm_gated(self, tool_name: str) -> bool:
        """Check if tool requires user confirmation."""
        return tool_name in self.confirm_gated


@dataclass
class ToolContext:
    """Runtime context passed to every MCP tool handler.

    Carries pre-resolved credentials (only for declared dependencies),
    permission state, and session metadata.
    """

    agent_name: str
    session_id: str
    permission_tier: PermissionTier
    credentials: dict[str, str]
    permissions: ToolPermissions
    break_glass_token: str | None = None
