"""Input parser for the Corvus TUI.

Classifies raw user input into one of four kinds:
- command:   /help, /agent homelab, /memory search "query"
- tool_call: !obsidian.search "query"
- mention:   @homelab check nginx, @homelab @finance status
- chat:      everything else
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_MENTION_RE = re.compile(r"@(\w+)")


@dataclass
class ParsedInput:
    """Result of parsing a single line of user input."""

    raw: str
    kind: str  # "command" | "tool_call" | "mention" | "chat"
    text: str
    command: str | None = None
    command_args: str | None = None
    tool_name: str | None = None
    tool_args: str | None = None
    mentions: list[str] = field(default_factory=list)

    @property
    def tool_params(self) -> dict | None:
        """Return tool arguments as a dict, or None if no tool args.

        Provides a structured accessor while keeping ``tool_args`` for
        backward compatibility.
        """
        if self.tool_args is None:
            return None
        return {"raw": self.tool_args}


class InputParser:
    """Stateful parser that knows which agent names are valid for @mentions."""

    def __init__(self, known_agents: list[str] | None = None) -> None:
        agents = set(known_agents) if known_agents else set()
        agents.add("all")
        self._known_agents: set[str] = agents

    def update_agents(self, agents: list[str]) -> None:
        """Add agents to the known set (keeps 'all')."""
        self._known_agents.update(agents)

    def parse(self, raw: str) -> ParsedInput:
        """Parse raw input and return a classified ParsedInput."""
        text = raw.strip()

        # 1. /command
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            command = parts[0] if parts else ""
            command_args = parts[1] if len(parts) > 1 else None
            return ParsedInput(
                raw=raw,
                kind="command",
                text=text,
                command=command,
                command_args=command_args,
            )

        # 2. !tool_call
        if text.startswith("!"):
            parts = text[1:].split(None, 1)
            tool_name = parts[0] if parts else ""
            tool_args = parts[1] if len(parts) > 1 else None
            return ParsedInput(
                raw=raw,
                kind="tool_call",
                text=text,
                tool_name=tool_name,
                tool_args=tool_args,
            )

        # 3. @mention (only if at least one mention is a known agent)
        if text.startswith("@"):
            matches = _MENTION_RE.findall(text)
            known_matches = [m for m in matches if m in self._known_agents]
            if known_matches:
                # Strip all @mentions from the front to get the remaining text
                remainder = _MENTION_RE.sub("", text).strip()
                # Bare @agent with no text → treat as /agent switch command
                if not remainder:
                    return ParsedInput(
                        raw=raw,
                        kind="command",
                        text=text,
                        command="agent",
                        command_args=known_matches[0],
                    )
                return ParsedInput(
                    raw=raw,
                    kind="mention",
                    text=remainder,
                    mentions=known_matches,
                )

        # 4. chat (default)
        return ParsedInput(raw=raw, kind="chat", text=text)
