"""Corvus TUI main application — chat loop and command dispatch."""

import asyncio
import logging

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console

load_dotenv()

from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.input.completer import ChatCompleter
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.theme import TuiTheme

logger = logging.getLogger("corvus-tui.app")


class TuiApp:
    """Main TUI application coordinating all components.

    Creates the theme, console, renderer, agent stack, command registry,
    command router, input parser, event handler, gateway, token counter,
    completer, and session manager on construction.
    """

    def __init__(self) -> None:
        self.theme = TuiTheme()
        self.console = Console()
        self.renderer = ChatRenderer(self.console, self.theme)
        self.agent_stack = AgentStack()
        self.command_registry = CommandRegistry()
        self.command_router = CommandRouter(self.command_registry)
        self.parser = InputParser()
        self.token_counter = TokenCounter()
        self.event_handler = EventHandler(self.renderer, self.agent_stack, self.token_counter)
        self.gateway = InProcessGateway()
        self.completer = ChatCompleter(self.command_registry)
        self.session_manager = TuiSessionManager(self.gateway, self.agent_stack)

        self._register_builtin_commands()

    # ------------------------------------------------------------------
    # Built-in command registration
    # ------------------------------------------------------------------

    def _register_builtin_commands(self) -> None:
        """Register all built-in slash commands with correct tiers."""
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

        service_commands = [
            SlashCommand(name="sessions", description="List all sessions", tier=InputTier.SERVICE),
            SlashCommand(name="session", description="Manage sessions (new/resume)", tier=InputTier.SERVICE, args_spec="<action> [id]"),
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
        """Build the prompt with agent path and token count."""
        tokens = self.token_counter.format_display()

        if self.agent_stack.depth == 0:
            return HTML(f"<b>corvus</b> <i>[{tokens}]</i>&gt; ")

        agent = self.agent_stack.current.agent_name
        if self.agent_stack.depth == 1:
            return HTML(f"<b>@{agent}</b> <i>[{tokens}]</i>&gt; ")

        breadcrumb = self.agent_stack.breadcrumb
        return HTML(f"<b>{breadcrumb}</b> <i>[{tokens}]</i>&gt; ")

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
                    marker = " *" if self.agent_stack.depth > 0 and self.agent_stack.current.agent_name == agent.get("id") else ""
                    self.renderer.render_system(f"  @{label}{marker} — {desc}")
            return True

        if cmd_name == "agent":
            agent_name = parsed.command_args
            if not agent_name:
                self.renderer.render_error("Usage: /agent <name>")
                return True
            agent_name = agent_name.strip()
            self.agent_stack.switch(agent_name, session_id="")
            self.renderer.render_system(f"Switched to @{agent_name}")
            return True

        return False

    async def _handle_service_command(self, parsed: ParsedInput) -> bool:
        """Handle service-tier commands. Returns True if handled."""
        cmd_name = parsed.command

        if cmd_name == "tokens":
            self.renderer.render_system(f"Session total: {self.token_counter.format_display()}")
            for agent, count in self.token_counter.all_agents.items():
                self.renderer.render_system(f"  @{agent}: {count:,} tokens")
            return True

        if cmd_name == "sessions":
            sessions = await self.session_manager.list_sessions()
            if not sessions:
                self.renderer.render_system("No sessions found.")
            else:
                self.renderer.render_system("Recent sessions:")
                for s in sessions:
                    self.renderer.render_system(f"  {self.session_manager.format_session_summary(s)}")
            return True

        if cmd_name == "session":
            args = parsed.command_args or ""
            parts = args.strip().split(maxsplit=1)
            if not parts:
                self.renderer.render_error("Usage: /session new | /session resume <id>")
                return True
            action = parts[0]
            if action == "new":
                agent = self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else "huginn"
                sid = await self.session_manager.create(agent)
                self.renderer.render_system(f"New session: {sid[:8]} (@{agent})")
            elif action == "resume" and len(parts) > 1:
                sid = parts[1]
                detail = await self.session_manager.resume(sid)
                agent = detail.agent_name or "unknown"
                msgs = detail.message_count
                self.renderer.render_system(f"Resumed session {sid[:8]} (@{agent}, {msgs} messages)")
            else:
                self.renderer.render_error("Usage: /session new | /session resume <id>")
            return True

        self.renderer.render_system(f"/{cmd_name} — not yet implemented")
        return True

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

        try:
            await self.gateway.send_message(text)
        except Exception as exc:
            self.renderer.render_error(f"Gateway error: {exc}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main chat loop: connect, load agents, read input, dispatch."""
        session: PromptSession = PromptSession(completer=self.completer)

        self.renderer.render_system("Connecting to Corvus gateway...")
        await self.gateway.connect()
        self.gateway.on_event(self.event_handler.handle)

        # Load agents and set up initial state
        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.parser.update_agents(agent_names)
        self.completer.update_agents(agent_names)

        if agent_names:
            default_agent = "huginn" if "huginn" in agent_names else agent_names[0]
            self.agent_stack.push(default_agent, session_id="")
            self.renderer.render_system(f"Ready. Talking to @{default_agent} ({len(agent_names)} agents available)")
        else:
            self.renderer.render_system("Ready. No agents loaded.")

        self.renderer.render_system("Type /help for commands. Tab to complete. /quit to exit.\n")

        try:
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
                    await self._handle_service_command(parsed)
                    continue

                await self._handle_agent_input(parsed)

        except KeyboardInterrupt:
            pass
        finally:
            await self.gateway.disconnect()
            self.renderer.render_system("Goodbye.")


def main() -> None:
    """Entry point for python -m corvus.tui."""
    import os

    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        filename="logs/tui.log",
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    app = TuiApp()
    asyncio.run(app.run())
