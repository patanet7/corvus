"""Corvus TUI main application — chat loop and command dispatch."""

import asyncio
import logging

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console

from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.theme import TuiTheme

logger = logging.getLogger("corvus-tui.app")


class TuiApp:
    """Main TUI application coordinating all components.

    Creates the theme, console, renderer, agent stack, command registry,
    command router, input parser, event handler, and gateway on construction.
    Registers all built-in slash commands and provides the main chat loop.
    """

    def __init__(self) -> None:
        self.theme = TuiTheme()
        self.console = Console()
        self.renderer = ChatRenderer(self.console, self.theme)
        self.agent_stack = AgentStack()
        self.command_registry = CommandRegistry()
        self.command_router = CommandRouter(self.command_registry)
        self.parser = InputParser()
        self.event_handler = EventHandler(self.renderer, self.agent_stack)
        self.gateway = InProcessGateway()

        self._register_builtin_commands()

    # ------------------------------------------------------------------
    # Built-in command registration
    # ------------------------------------------------------------------

    def _register_builtin_commands(self) -> None:
        """Register all built-in slash commands with correct tiers."""
        # SYSTEM tier
        system_commands = [
            SlashCommand(name="help", description="Show available commands", tier=InputTier.SYSTEM),
            SlashCommand(name="quit", description="Exit the TUI", tier=InputTier.SYSTEM),
            SlashCommand(name="agents", description="List all available agents", tier=InputTier.SYSTEM),
            SlashCommand(name="agent", description="Switch to a specific agent", tier=InputTier.SYSTEM, args_spec="<name>"),
            SlashCommand(name="models", description="List available models", tier=InputTier.SYSTEM),
            SlashCommand(name="model", description="Switch to a specific model", tier=InputTier.SYSTEM, args_spec="<name>"),
            SlashCommand(name="reload", description="Reload agent configuration", tier=InputTier.SYSTEM),
            SlashCommand(name="setup", description="Run interactive setup wizard", tier=InputTier.SYSTEM),
            SlashCommand(name="breakglass", description="Enable break-glass mode", tier=InputTier.SYSTEM),
            SlashCommand(name="focus", description="Focus a pane or agent", tier=InputTier.SYSTEM, args_spec="<target>"),
            SlashCommand(name="split", description="Split the terminal view", tier=InputTier.SYSTEM, args_spec="<direction>"),
            SlashCommand(name="theme", description="Change the TUI theme", tier=InputTier.SYSTEM, args_spec="[name]"),
        ]

        # SERVICE tier
        service_commands = [
            SlashCommand(name="sessions", description="List all sessions", tier=InputTier.SERVICE),
            SlashCommand(name="session", description="Switch to or view a session", tier=InputTier.SERVICE, args_spec="<id>"),
            SlashCommand(name="memory", description="Search or manage memory", tier=InputTier.SERVICE, args_spec="<action> [query]"),
            SlashCommand(name="tools", description="List available tools", tier=InputTier.SERVICE),
            SlashCommand(name="tool", description="View tool details", tier=InputTier.SERVICE, args_spec="<name>"),
            SlashCommand(name="tool-history", description="View tool call history", tier=InputTier.SERVICE),
            SlashCommand(name="view", description="View a file or resource", tier=InputTier.SERVICE, args_spec="<path>"),
            SlashCommand(name="edit", description="Edit a file or resource", tier=InputTier.SERVICE, args_spec="<path>"),
            SlashCommand(name="diff", description="Show diff of changes", tier=InputTier.SERVICE, args_spec="[path]"),
            SlashCommand(name="workers", description="List active worker agents", tier=InputTier.SERVICE),
            SlashCommand(name="tokens", description="Show token usage", tier=InputTier.SERVICE),
            SlashCommand(name="status", description="Show system status", tier=InputTier.SERVICE),
            SlashCommand(name="export", description="Export session or data", tier=InputTier.SERVICE, args_spec="<format> [path]"),
            SlashCommand(name="audit", description="View audit log", tier=InputTier.SERVICE),
            SlashCommand(name="policy", description="View or modify tool policies", tier=InputTier.SERVICE, args_spec="[action]"),
        ]

        # AGENT tier
        agent_commands = [
            SlashCommand(name="spawn", description="Spawn a child agent in background", tier=InputTier.AGENT, args_spec="<name>", agent_scoped=True),
            SlashCommand(name="enter", description="Enter a child agent", tier=InputTier.AGENT, args_spec="<name>", agent_scoped=True),
            SlashCommand(name="back", description="Go back to parent agent", tier=InputTier.AGENT, agent_scoped=True),
            SlashCommand(name="top", description="Return to root agent", tier=InputTier.AGENT, agent_scoped=True),
            SlashCommand(name="summon", description="Summon an agent to current context", tier=InputTier.AGENT, args_spec="<name>", agent_scoped=True),
            SlashCommand(name="kill", description="Kill a child agent", tier=InputTier.AGENT, args_spec="<name>", agent_scoped=True),
        ]

        for cmd in system_commands + service_commands + agent_commands:
            self.command_registry.register(cmd)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(self) -> HTML:
        """Build the prompt showing the current agent path."""
        if self.agent_stack.depth == 0:
            return HTML("<b>corvus</b>&gt; ")
        if self.agent_stack.depth == 1:
            agent = self.agent_stack.current.agent_name
            color = self.theme.agent_color(agent)
            return HTML(f"<b>@{agent}</b>&gt; ")
        breadcrumb = self.agent_stack.breadcrumb
        return HTML(f"<b>{breadcrumb}</b>&gt; ")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_system_command(self, parsed: ParsedInput) -> bool:
        """Handle system-tier commands. Returns True if handled."""
        cmd_name = parsed.command

        if cmd_name == "help":
            self.renderer.render_system("Available commands:")
            for tier in (InputTier.SYSTEM, InputTier.SERVICE, InputTier.AGENT):
                commands = self.command_registry.commands_for_tier(tier)
                if commands:
                    self.renderer.render_system(f"\n  [{tier.value.upper()}]")
                    for cmd in sorted(commands, key=lambda c: c.name):
                        args_hint = f" {cmd.args_spec}" if cmd.args_spec else ""
                        self.renderer.render_system(f"    /{cmd.name}{args_hint} — {cmd.description}")
            return True

        if cmd_name == "quit":
            raise KeyboardInterrupt

        if cmd_name == "agents":
            agents = await self.gateway.list_agents()
            if not agents:
                self.renderer.render_system("No agents available.")
            else:
                self.renderer.render_system("Available agents:")
                for agent in agents:
                    label = agent.get("label", agent.get("id", "unknown"))
                    desc = agent.get("description", "")
                    self.renderer.render_system(f"  {label} — {desc}")
            return True

        if cmd_name == "agent":
            agent_name = parsed.command_args
            if not agent_name:
                self.renderer.render_error("Usage: /agent <name>")
                return True
            agent_name = agent_name.strip()
            self.agent_stack.switch(agent_name, session_id="")
            self.parser.update_agents([agent_name])
            self.renderer.render_system(f"Switched to @{agent_name}")
            return True

        return False

    async def _handle_agent_input(self, parsed: ParsedInput) -> None:
        """Handle agent-tier input: chat, mentions, and agent commands."""
        cmd_name = parsed.command

        if cmd_name == "back":
            try:
                popped = self.agent_stack.pop()
                self.renderer.render_system(f"Left @{popped.agent_name}")
            except IndexError:
                self.renderer.render_error("Already at root agent")
            return

        if cmd_name == "top":
            try:
                root = self.agent_stack.pop_to_root()
                self.renderer.render_system(f"Returned to @{root.agent_name}")
            except IndexError:
                self.renderer.render_error("Agent stack is empty")
            return

        if cmd_name == "enter":
            target = parsed.command_args
            if not target:
                self.renderer.render_error("Usage: /enter <agent>")
                return
            try:
                entered = self.agent_stack.enter(target.strip())
                self.renderer.render_system(f"Entered @{entered.agent_name}")
            except KeyError as exc:
                self.renderer.render_error(str(exc))
            return

        if cmd_name == "kill":
            target = parsed.command_args
            if not target:
                self.renderer.render_error("Usage: /kill <agent>")
                return
            try:
                killed = self.agent_stack.kill(target.strip())
                self.renderer.render_system(f"Killed @{killed.agent_name}")
            except KeyError as exc:
                self.renderer.render_error(str(exc))
            return

        # Chat or mention — send to gateway
        if parsed.kind == "mention":
            text = parsed.text
            if parsed.mentions:
                text = f"@{parsed.mentions[0]} {text}"
        else:
            text = parsed.text

        if self.agent_stack.depth > 0:
            agent = self.agent_stack.current.agent_name
            self.renderer.render_user_message(text, agent)
        else:
            self.renderer.render_user_message(text, "corvus")

        await self.gateway.send_message(text)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main chat loop: connect, load agents, read input, dispatch."""
        session: PromptSession = PromptSession()

        self.renderer.render_system("Connecting to Corvus gateway...")
        await self.gateway.connect()
        self.gateway.on_event(self.event_handler.handle)

        # Load agents and set up initial state
        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.parser.update_agents(agent_names)

        if agent_names:
            default_agent = agent_names[0]
            self.agent_stack.push(default_agent, session_id="")
            self.renderer.render_system(f"Ready. Current agent: @{default_agent}")
        else:
            self.renderer.render_system("Ready. No agents loaded.")

        self.renderer.render_system("Type /help for available commands, /quit to exit.\n")

        try:
            with patch_stdout():
                while True:
                    try:
                        prompt = self._build_prompt()
                        raw = await session.prompt_async(prompt)
                    except EOFError:
                        break
                    except KeyboardInterrupt:
                        break

                    if not raw or not raw.strip():
                        continue

                    parsed = self.parser.parse(raw)
                    tier = self.command_router.classify(parsed)

                    # Handle pending confirmation
                    pending = self.event_handler.pending_confirm
                    if pending is not None:
                        response = raw.strip().lower()
                        if response in ("y", "yes"):
                            await self.gateway.respond_confirm(pending.tool_id, approved=True)
                        elif response in ("n", "no"):
                            await self.gateway.respond_confirm(pending.tool_id, approved=False)
                        elif response in ("a", "always"):
                            await self.gateway.respond_confirm(pending.tool_id, approved=True)
                        else:
                            self.renderer.render_error("Please respond with (y)es, (n)o, or (a)lways")
                            continue
                        self.event_handler.clear_confirm()
                        continue

                    if tier is InputTier.SYSTEM:
                        handled = await self._handle_system_command(parsed)
                        if handled:
                            continue

                    if tier is InputTier.SERVICE:
                        self.renderer.render_system(f"/{parsed.command} — not yet implemented")
                        continue

                    await self._handle_agent_input(parsed)

        except KeyboardInterrupt:
            pass
        finally:
            await self.gateway.disconnect()
            self.renderer.render_system("Goodbye.")


def main() -> None:
    """Entry point for python -m corvus.tui."""
    app = TuiApp()
    asyncio.run(app.run())
