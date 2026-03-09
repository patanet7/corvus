"""Three-tier command router for the Corvus TUI.

Classifies parsed input into SYSTEM, SERVICE, or AGENT tiers based on
whether the input is a known slash command and which tier it belongs to.
All non-command input (chat, mentions, tool calls) routes to AGENT.
"""

from __future__ import annotations

from corvus.tui.commands.registry import CommandRegistry, InputTier
from corvus.tui.input.parser import ParsedInput


class CommandRouter:
    """Routes parsed input to the appropriate processing tier."""

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def classify(self, parsed: ParsedInput) -> InputTier:
        """Classify parsed input into a processing tier.

        If the input is a known slash command, returns that command's tier.
        Everything else (chat, mentions, tool calls, unknown commands)
        returns InputTier.AGENT.
        """
        if parsed.kind == "command" and parsed.command is not None:
            cmd = self._registry.lookup(parsed.command)
            if cmd is not None:
                return cmd.tier
        return InputTier.AGENT
