"""RuntimeAdapter — abstracts CLI-specific concerns for portability.

Security contract for all adapters:
- MUST apply env whitelist (never pass full os.environ)
- MUST compose permissions.deny from policy engine output
- MUST disable marketplace/plugins in settings
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from corvus.security.tool_context import PermissionTier


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Protocol for runtime-specific concerns.

    Implementations handle settings file composition, launch command
    construction, and other runtime-specific details. All security
    logic lives in the runtime-agnostic layers (PolicyEngine, ToolContext).
    """

    def compose_permissions(
        self,
        tier: PermissionTier,
        global_deny: list[str],
        extra_deny: list[str],
    ) -> dict: ...

    def compose_settings(self, deny: list[str]) -> str: ...

    def build_launch_cmd(
        self,
        workspace: Path,
        mcp_config: dict,
        system_prompt: str,
        model: str | None,
    ) -> list[str]: ...


class ClaudeCodeAdapter:
    """Adapter for Claude Code CLI as the agent runtime."""

    def compose_permissions(
        self,
        tier: PermissionTier,
        global_deny: list[str],
        extra_deny: list[str],
    ) -> dict:
        deny = sorted(set(global_deny + extra_deny))
        return {"deny": deny}

    def compose_settings(self, deny: list[str]) -> str:
        return json.dumps(
            {
                "permissions": {"deny": deny},
                "enabledPlugins": {},
                "strictKnownMarketplaces": [],
            },
            indent=2,
        )

    def build_launch_cmd(
        self,
        workspace: Path,
        mcp_config: dict,
        system_prompt: str,
        model: str | None,
    ) -> list[str]:
        cmd = ["claude", "--print", "--verbose"]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--setting-sources", "user,project"])
        return cmd
