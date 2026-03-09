"""Tab completion for the Corvus TUI chat input.

Provides completions for:
- ``/`` prefix: slash commands (from CommandRegistry)
- ``/command <arg>``: contextual argument completions (agent names, etc.)
- ``@`` prefix: agent names (anywhere in line)
- ``!`` prefix: tool names
"""

from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from corvus.tui.commands.registry import CommandRegistry

# Commands whose argument is an agent name.
_AGENT_ARG_COMMANDS = frozenset({
    "agent", "enter", "spawn", "summon", "kill", "focus",
})


class ChatCompleter(Completer):
    """Tab completion for @agents, /commands, /command args, and !tools."""

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

        # /command argument completions — "/agent ho" → complete agent names
        if text.startswith("/") and " " in text:
            space_pos = text.index(" ")
            cmd_name = text[1:space_pos]
            arg_partial = text[space_pos + 1 :]

            if cmd_name in _AGENT_ARG_COMMANDS:
                for name in sorted(self._agent_names):
                    if name.startswith(arg_partial):
                        yield Completion(
                            name,
                            start_position=-(len(arg_partial)),
                            display_meta="agent",
                        )
                return

            # Fall through — no special arg completion for this command
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
