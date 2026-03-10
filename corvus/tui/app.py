"""Corvus TUI main application — chat loop and command dispatch."""

import argparse
import asyncio
import html
import os
from pathlib import Path

import structlog
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console

load_dotenv()

from corvus.security.audit import AuditLog
from corvus.security.policy import PolicyEngine
from corvus.tui.commands.builtins import (
    ServiceCommandHandler,
    SystemCommandHandler,
    _detect_language,
)
from corvus.tui.core.credentials import _get_credential_status
from corvus.tui.commands.domain import AgentCommandHandler
from corvus.tui.protocol.base import GatewayProtocol
from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.agent_stack import AgentStack, AgentStatus
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.core.split_manager import SplitManager
from corvus.tui.input.completer import ChatCompleter
from corvus.tui.input.editor import ChatEditor
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.protocol.websocket import WebSocketGateway
from corvus.logging import configure_logging
from corvus.tui.theme import TuiTheme, available_themes

logger = structlog.get_logger(__name__)


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
        self.status_bar = StatusBar(self.agent_stack, self.token_counter, self.theme)
        self.session_manager = TuiSessionManager(self.gateway, self.agent_stack)
        self._always_allow: set[str] = set()
        self.split_manager = SplitManager()
        self._editor = ChatEditor(completer=self.completer)
        self._editor.set_clear_callback(lambda: self.console.clear())
        self._editor.set_sidebar_callback(
            lambda: self._sidebar.toggle() if hasattr(self, "_sidebar") else None
        )

        # Audit log — only initialised when CORVUS_AUDIT_LOG is set or logs/ exists
        audit_path = os.environ.get("CORVUS_AUDIT_LOG", "")
        if not audit_path and os.path.isdir("logs"):
            audit_path = "logs/audit.jsonl"
        audit_log_inst: AuditLog | None = AuditLog(Path(audit_path)) if audit_path else None

        # Command handlers — own all command dispatch logic
        self._sys_handler = SystemCommandHandler(
            renderer=self.renderer,
            agent_stack=self.agent_stack,
            command_registry=self.command_registry,
            gateway=self.gateway,
            parser=self.parser,
            completer=self.completer,
            split_manager=self.split_manager,
            status_bar=self.status_bar,
            token_counter=self.token_counter,
        )
        self._sys_handler.theme = self.theme
        self._sys_handler.console = self.console

        self._svc_handler = ServiceCommandHandler(
            renderer=self.renderer,
            agent_stack=self.agent_stack,
            gateway=self.gateway,
            token_counter=self.token_counter,
            session_manager=self.session_manager,
            audit_log=audit_log_inst,
            policy_engine_ref=self._sys_handler,
        )

        self._agent_handler = AgentCommandHandler(
            renderer=self.renderer,
            agent_stack=self.agent_stack,
        )

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
            SlashCommand(name="login", description="Authenticate with session token", tier=InputTier.SYSTEM),
            SlashCommand(name="panel", description="Toggle sidebar panel", tier=InputTier.SYSTEM),
            SlashCommand(name="config", description="Show configuration info", tier=InputTier.SYSTEM),
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
    # Properties that propagate to handler classes
    # ------------------------------------------------------------------

    @property
    def renderer(self) -> ChatRenderer:
        return self._renderer

    @renderer.setter
    def renderer(self, value: ChatRenderer) -> None:
        self._renderer = value
        if hasattr(self, "_sys_handler"):
            self._sys_handler.renderer = value
        if hasattr(self, "_svc_handler"):
            self._svc_handler.renderer = value
        if hasattr(self, "_agent_handler"):
            self._agent_handler.renderer = value

    @property
    def gateway(self) -> GatewayProtocol:
        return self._gateway

    @gateway.setter
    def gateway(self, value: GatewayProtocol) -> None:
        self._gateway = value
        if hasattr(self, "_sys_handler"):
            self._sys_handler.gateway = value
        if hasattr(self, "_svc_handler"):
            self._svc_handler.gateway = value

    @property
    def session_manager(self) -> TuiSessionManager:
        return self._session_manager

    @session_manager.setter
    def session_manager(self, value: TuiSessionManager) -> None:
        self._session_manager = value
        if hasattr(self, "_svc_handler"):
            self._svc_handler.session_manager = value

    # ------------------------------------------------------------------
    # Proxy properties — delegate to handler classes for backward compat
    # ------------------------------------------------------------------

    @property
    def policy_engine(self) -> PolicyEngine | None:
        return self._sys_handler.policy_engine

    @policy_engine.setter
    def policy_engine(self, value: PolicyEngine | None) -> None:
        self._sys_handler.policy_engine = value

    @property
    def permission_tier(self) -> str:
        return self._sys_handler.permission_tier

    @permission_tier.setter
    def permission_tier(self, value: str) -> None:
        self._sys_handler.permission_tier = value

    @property
    def _break_glass_token(self) -> str | None:
        return self._sys_handler._break_glass_token

    @_break_glass_token.setter
    def _break_glass_token(self, value: str | None) -> None:
        self._sys_handler._break_glass_token = value

    @property
    def _break_glass_expiry(self) -> float | None:
        return self._sys_handler._break_glass_expiry

    @_break_glass_expiry.setter
    def _break_glass_expiry(self, value: float | None) -> None:
        self._sys_handler._break_glass_expiry = value

    @property
    def _break_glass_secret(self) -> bytes:
        return self._sys_handler._break_glass_secret

    @property
    def _audit_log(self) -> AuditLog | None:
        if hasattr(self, "_svc_handler"):
            return self._svc_handler.audit_log
        return getattr(self, "_audit_log_backing", None)

    @_audit_log.setter
    def _audit_log(self, value: AuditLog | None) -> None:
        if hasattr(self, "_svc_handler"):
            self._svc_handler.audit_log = value
        else:
            self._audit_log_backing = value

    # ------------------------------------------------------------------
    # Proxy methods — delegate to handler classes for backward compat
    # ------------------------------------------------------------------

    async def _handle_breakglass_command(self, args: str | None) -> None:
        await self._sys_handler._handle_breakglass(args)

    def _handle_setup_command(self, args: str | None) -> None:
        self._sys_handler._handle_setup(args)

    def _get_credential_status(self) -> list[dict]:
        return _get_credential_status()

    async def _handle_memory_command(self, args: str) -> bool:
        return await self._svc_handler._handle_memory(args)

    def _handle_view_command(self, args: str) -> bool:
        return self._svc_handler._handle_view(args)

    def _handle_edit_command(self, args: str) -> bool:
        return self._svc_handler._handle_edit(args)

    def _handle_diff_command(self, args: str) -> bool:
        return self._svc_handler._handle_diff(args)

    async def _handle_export_command(self, args: str | None) -> None:
        await self._svc_handler._handle_export(args)

    def _handle_audit_command(self, args: str | None) -> None:
        if hasattr(self, "_svc_handler"):
            self._svc_handler._handle_audit(args)
        else:
            self.renderer.render_system("Audit log not available (app not fully initialized)")

    async def _handle_policy_command(self) -> None:
        self._svc_handler._handle_policy()

    def _handle_workers_command(self) -> None:
        self._svc_handler._handle_workers()

    async def _handle_status_command(self) -> None:
        await self._svc_handler._handle_status()

    def _handle_tool_history_command(self) -> None:
        self._svc_handler._handle_tool_history()

    @staticmethod
    def _detect_language(path: str) -> str:
        return _detect_language(path)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(self) -> HTML:
        """Build the prompt with agent path (token count is in the status bar)."""
        if self.agent_stack.depth == 0:
            return HTML("<b>corvus</b>&gt; ")

        agent = html.escape(self.agent_stack.current.agent_name)
        if self.agent_stack.depth == 1:
            return HTML(f"<b>@{agent}</b>&gt; ")

        breadcrumb = html.escape(self.agent_stack.breadcrumb)
        return HTML(f"<b>{breadcrumb}</b>&gt; ")

    # ------------------------------------------------------------------
    # Always-allow helpers
    # ------------------------------------------------------------------

    def is_tool_always_allowed(self, tool_name: str) -> bool:
        """Check if a tool has been marked as always-allow."""
        return tool_name in self._always_allow

    def mark_tool_always_allow(self, tool_name: str) -> None:
        """Mark a tool as always-allowed for this session."""
        self._always_allow.add(tool_name)

    # ------------------------------------------------------------------
    # Command dispatch (delegates to handler classes)
    # ------------------------------------------------------------------

    async def _handle_system_command(self, parsed: ParsedInput) -> bool:
        """Delegate system-tier commands to SystemCommandHandler."""
        handled = await self._sys_handler.handle(parsed)

        # Note: pending_login is handled in the main loop before parsing

        # Check for deferred theme switch
        new_theme = self._sys_handler.pending_theme_switch
        if new_theme is not None:
            self._sys_handler.clear_theme_switch()
            self.theme = TuiTheme(new_theme)
            self.renderer = ChatRenderer(self.console, self.theme)
            self.event_handler = EventHandler(self.renderer, self.agent_stack, self.token_counter)
            self.status_bar = StatusBar(self.agent_stack, self.token_counter, self.theme)
            # Update handler references to new renderer/status_bar
            self._sys_handler.renderer = self.renderer
            self._sys_handler.status_bar = self.status_bar
            self._sys_handler.theme = self.theme
            self._svc_handler.renderer = self.renderer
            self.renderer.render_system(f"Theme switched to '{new_theme}'")

        return handled

    async def _handle_service_command(self, parsed: ParsedInput) -> bool:
        """Delegate service-tier commands to ServiceCommandHandler."""
        return await self._svc_handler.handle(parsed)

    # ------------------------------------------------------------------
    # Agent input handling
    # ------------------------------------------------------------------

    async def _handle_agent_input(self, parsed: ParsedInput) -> None:
        """Handle agent-tier input: chat, mentions, tool calls, and agent commands."""
        if not parsed.text.strip():
            return

        # Delegate agent navigation commands to AgentCommandHandler
        handled = await self._agent_handler.handle(parsed)
        if handled:
            # For /spawn with task text, forward the task to the spawned agent
            if parsed.command == "spawn" and parsed.command_args:
                parts = parsed.command_args.strip().split(None, 1)
                if len(parts) > 1:
                    agent_name = parts[0]
                    task_text = parts[1].strip().strip('"').strip("'")
                    if task_text:
                        try:
                            await self.gateway.send_message(task_text, requested_agent=agent_name)
                        except Exception as exc:
                            self.renderer.render_error(f"Failed to send task to @{agent_name}: {exc}")
            return

        # !tool dispatch — send as a message, agent interprets the ! prefix
        if parsed.kind == "tool_call":
            text = f"!{parsed.tool_name}"
            if parsed.tool_args:
                text += f" {parsed.tool_args}"

            if self.agent_stack.depth > 0:
                target = self.agent_stack.current.agent_name
                target = None if target == "huginn" else target
            else:
                target = None

            self.renderer.render_user_message(text, target or "corvus")
            try:
                await self.gateway.send_message(text, requested_agent=target)
            except Exception as exc:
                self.renderer.render_error(f"Gateway error: {exc}")
            return

        # Chat or mention — send to gateway
        if parsed.kind == "mention":
            text = parsed.text
            mention_target = parsed.mentions[0] if parsed.mentions else None
            if mention_target:
                text = f"@{mention_target} {text}"
        else:
            text = parsed.text
            mention_target = None

        if self.agent_stack.depth > 0:
            agent = self.agent_stack.current.agent_name
            self.renderer.render_user_message(text, mention_target or agent)
        else:
            self.renderer.render_user_message(text, mention_target or "corvus")

        # Route: mention target overrides stack selection; huginn passes None (let router decide)
        if mention_target and mention_target != "huginn":
            target = mention_target
        elif self.agent_stack.depth > 0:
            selected = self.agent_stack.current.agent_name
            target = None if selected == "huginn" else selected
        else:
            target = None

        try:
            await self.gateway.send_message(text, requested_agent=target)
        except Exception as exc:
            self.renderer.render_error(f"Gateway error: {exc}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main chat loop: connect, load agents, read input, dispatch."""
        self.renderer.render_system("Connecting to Corvus gateway...")
        await self.gateway.connect()
        self.gateway.on_event(self.event_handler.handle)

        # Wire auto-approve for always-allowed tools
        def _auto_approve_confirm(tool_id: str, _action: str) -> None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.gateway.respond_confirm(tool_id, approved=True))
            except RuntimeError:
                pass

        self.event_handler.set_auto_approve(
            check_fn=self.is_tool_always_allowed,
            confirm_fn=_auto_approve_confirm,
        )

        # Load agents and set up initial state
        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.parser.update_agents(agent_names)
        self.completer.update_agents(agent_names)

        if agent_names:
            default_agent = "huginn" if "huginn" in agent_names else agent_names[0]
            self.agent_stack.push(default_agent, session_id="")
            self.renderer.render_welcome(len(agent_names), default_agent)
        else:
            self.renderer.render_system("Ready. No agents loaded. Type /help for commands.")

        try:
            while True:
                # Check break-glass TTL expiry
                self._sys_handler.check_breakglass_expiry()

                try:
                    prompt = self._build_prompt()
                    raw = await self._editor.prompt(prompt, bottom_toolbar=self.status_bar)
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break

                if not raw or not raw.strip():
                    continue

                # Handle pending login — treat raw input as a session token
                if self._sys_handler.pending_login:
                    self._sys_handler.clear_pending_login()
                    await self._sys_handler.complete_login(raw.strip())
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
                        self.mark_tool_always_allow(pending.tool)
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
    parser = argparse.ArgumentParser(description="Corvus TUI — terminal chat interface")
    parser.add_argument(
        "--mode",
        choices=["inprocess", "websocket"],
        default="inprocess",
        help="Gateway mode: inprocess (default) or websocket",
    )
    parser.add_argument(
        "--url",
        default="ws://localhost:8000/ws",
        help="WebSocket server URL (only used with --mode websocket)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CORVUS_SESSION_TOKEN"),
        help="Session token for WebSocket auth (or set CORVUS_SESSION_TOKEN)",
    )
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)
    configure_logging(log_file="logs/tui.log")

    app = TuiApp()

    if args.mode == "websocket":
        app.gateway = WebSocketGateway(url=args.url, token=args.token)
        app.session_manager = TuiSessionManager(app.gateway, app.agent_stack)

    asyncio.run(app.run())
