"""Tab completion for the Corvus TUI chat input.

Provides completions for three prefix types:
- ``@`` prefix: agent names
- ``/`` prefix: slash commands (from CommandRegistry)
- ``!`` prefix: tool names
"""

from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from corvus.tui.commands.registry import CommandRegistry


class ChatCompleter(Completer):
    """Tab completion for @agents, /commands, and !tools."""

    def __init__(
        self,
        command_registry: CommandRegistry,
        agent_names: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> None:
        self._registry = command_registry
        self._agent_names: list[str] = agent_names or []
        self._tool_names: list[str] = tool_names or []

    def update_agents(self, names: list[str]) -> None:
        """Replace the set of available agent names."""
        self._agent_names = list(names)

    def update_tools(self, names: list[str]) -> None:
        """Replace the set of available tool names."""
        self._tool_names = list(names)

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterable[Completion]:
        """Yield completions based on the text before the cursor."""
        text = document.text_before_cursor

        # @agent completions — triggered anywhere in the line
        if "@" in text:
            at_pos = text.rfind("@")
            partial = text[at_pos + 1 :]
            for name in sorted(self._agent_names):
                if name.startswith(partial):
                    yield Completion(
                        name,
                        start_position=-(len(partial)),
                        display_meta="agent",
                    )
            return

        # /command completions — only at the start of the line
        if text.startswith("/"):
            partial = text[1:]
            for name in self._registry.completions(partial):
                cmd = self._registry.lookup(name)
                meta = cmd.description if cmd else ""
                yield Completion(
                    "/" + name,
                    start_position=-(len(text)),
                    display_meta=meta,
                )
            return

        # !tool completions — only at the start of the line
        if text.startswith("!"):
            partial = text[1:]
            for name in sorted(self._tool_names):
                if name.startswith(partial):
                    yield Completion(
                        "!" + name,
                        start_position=-(len(text)),
                        display_meta="tool",
                    )
            return
