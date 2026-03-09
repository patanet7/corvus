"""Agent-scoped command dispatch for the Corvus TUI.

Handles agent-tier slash commands that manipulate the agent navigation stack:
/spawn, /enter, /back, /top, /summon, /kill.
"""

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.input.parser import ParsedInput
from corvus.tui.output.renderer import ChatRenderer

# Commands handled by this handler, used for fast membership checks.
_AGENT_COMMANDS: frozenset[str] = frozenset({
    "back", "top", "enter", "kill", "summon", "spawn",
})


class AgentCommandHandler:
    """Handles agent-tier commands that navigate or manage the agent stack.

    Commands:
        /back         — Pop the current agent and return to its parent.
        /top          — Pop all agents except the root.
        /enter <name> — Enter an existing child agent by name.
        /spawn <name> — Spawn a child agent in the background.
        /summon <name> — Spawn a child and announce it as a coworker.
        /kill <name>  — Kill (remove) a child agent by name.
    """

    def __init__(
        self,
        renderer: ChatRenderer,
        agent_stack: AgentStack,
    ) -> None:
        self.renderer = renderer
        self.agent_stack = agent_stack

    async def handle(self, parsed: ParsedInput) -> bool:
        """Dispatch an agent-tier command.

        Returns True if the command was recognized and handled, False otherwise.
        """
        cmd = parsed.command
        if cmd not in _AGENT_COMMANDS:
            return False

        if cmd == "back":
            return self._handle_back()
        if cmd == "top":
            return self._handle_top()
        if cmd == "enter":
            return self._handle_enter(parsed.command_args)
        if cmd == "spawn":
            return self._handle_spawn(parsed.command_args)
        if cmd == "summon":
            return self._handle_summon(parsed.command_args)
        if cmd == "kill":
            return self._handle_kill(parsed.command_args)

        return False

    def _handle_back(self) -> bool:
        """Pop the current agent off the stack."""
        try:
            popped = self.agent_stack.pop()
            self.renderer.render_system(f"Left @{popped.agent_name}")
        except IndexError:
            self.renderer.render_error("Already at root agent")
        return True

    def _handle_top(self) -> bool:
        """Pop all agents except the root."""
        try:
            root = self.agent_stack.pop_to_root()
            self.renderer.render_system(f"Returned to @{root.agent_name}")
        except IndexError:
            self.renderer.render_error("Agent stack is empty")
        return True

    def _handle_enter(self, args: str | None) -> bool:
        """Enter an existing child agent by name."""
        if not args:
            self.renderer.render_error("Usage: /enter <agent>")
            return True
        try:
            entered = self.agent_stack.enter(args.strip())
            self.renderer.render_system(f"Entered @{entered.agent_name}")
        except KeyError as exc:
            self.renderer.render_error(str(exc))
        return True

    def _handle_spawn(self, args: str | None) -> bool:
        """Spawn a child agent in the background without entering it.

        Accepts ``/spawn <agent>`` or ``/spawn <agent> "task"``.
        The task string (if present) is handled by the caller after spawn.
        """
        if not args:
            self.renderer.render_error('Usage: /spawn <agent> ["task"]')
            return True
        parts = args.strip().split(None, 1)
        target = parts[0]
        self.agent_stack.spawn(target, session_id="")
        self.renderer.render_system(
            f"Spawned @{target} as background child of @{self.agent_stack.current.agent_name}"
        )
        return True

    def _handle_summon(self, args: str | None) -> bool:
        """Summon an agent as a coworker of the current agent."""
        if not args:
            self.renderer.render_error("Usage: /summon <agent>")
            return True
        target = args.strip()
        self.agent_stack.spawn(target, session_id="")
        self.renderer.render_system(
            f"Summoned @{target} as coworker of @{self.agent_stack.current.agent_name}"
        )
        return True

    def _handle_kill(self, args: str | None) -> bool:
        """Kill a child agent by name."""
        if not args:
            self.renderer.render_error("Usage: /kill <agent>")
            return True
        try:
            killed = self.agent_stack.kill(args.strip())
            self.renderer.render_system(f"Killed @{killed.agent_name}")
        except KeyError as exc:
            self.renderer.render_error(str(exc))
        return True
