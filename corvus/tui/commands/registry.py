"""Command registry for the Corvus TUI.

Provides a three-tier classification system (SYSTEM, SERVICE, AGENT) and a
registry that maps slash-command names to their definitions.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass


class InputTier(enum.Enum):
    """Three-tier classification for input routing."""

    SYSTEM = "system"
    SERVICE = "service"
    AGENT = "agent"


@dataclass(slots=True)
class SlashCommand:
    """Definition of a single slash command."""

    name: str
    description: str
    tier: InputTier
    handler: Callable | None = None
    args_spec: str | None = None
    agent_scoped: bool = False


class CommandRegistry:
    """Registry mapping command names to SlashCommand definitions."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        """Register a slash command by name."""
        self._commands[command.name] = command

    def lookup(self, name: str) -> SlashCommand | None:
        """Look up a command by name, returning None if not found."""
        return self._commands.get(name)

    def completions(self, partial: str) -> list[str]:
        """Return sorted command names matching the given prefix."""
        return sorted(
            name for name in self._commands if name.startswith(partial)
        )

    def all_commands(self) -> list[SlashCommand]:
        """Return all registered commands."""
        return list(self._commands.values())

    def commands_for_tier(self, tier: InputTier) -> list[SlashCommand]:
        """Return all commands belonging to the given tier."""
        return [cmd for cmd in self._commands.values() if cmd.tier is tier]
