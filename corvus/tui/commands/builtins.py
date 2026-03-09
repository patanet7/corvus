"""Built-in command handlers for the Corvus TUI.

Extracted from TuiApp to keep the main app module focused on coordination.
Each handler class groups related commands and receives dependencies via __init__.
"""

import os
import secrets
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from corvus.security.audit import AuditLog
from corvus.security.policy import PolicyEngine
from corvus.security.tokens import create_break_glass_token
from corvus.tui.commands.registry import CommandRegistry, InputTier
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.exporter import default_export_path, export_session_to_markdown
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.core.split_manager import SplitManager
from corvus.tui.input.completer import ChatCompleter
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.base import GatewayProtocol
from corvus.tui.protocol.websocket import WebSocketGateway
from corvus.tui.theme import TuiTheme, available_themes

if TYPE_CHECKING:
    from corvus.tui.core.event_handler import EventHandler


# ======================================================================
# System command handlers
# ======================================================================


class SystemCommandHandler:
    """Handles system-tier commands: help, quit, agents, agent, models, reload,
    setup, theme, split, breakglass."""

    _DEFAULT_BREAKGLASS_TTL_MINUTES: int = 60

    def __init__(
        self,
        *,
        renderer: ChatRenderer,
        agent_stack: AgentStack,
        command_registry: CommandRegistry,
        gateway: GatewayProtocol,
        parser: InputParser,
        completer: ChatCompleter,
        split_manager: SplitManager,
        status_bar: StatusBar,
        token_counter: TokenCounter,
    ) -> None:
        self.renderer = renderer
        self.agent_stack = agent_stack
        self.command_registry = command_registry
        self.gateway = gateway
        self.parser = parser
        self.completer = completer
        self.split_manager = split_manager
        self.status_bar = status_bar
        self.token_counter = token_counter

        # Theme state (mutable — swapped on theme change)
        self.theme: TuiTheme | None = None
        self.console = None  # Set by app after construction

        # Login state — pending token entry
        self._pending_login: bool = False

        # Policy engine and break-glass state
        self.policy_engine: PolicyEngine | None = None
        self.permission_tier: str = "default"
        self._break_glass_token: str | None = None
        self._break_glass_expiry: float | None = None
        self._break_glass_secret: bytes = secrets.token_bytes(32)

    # -- Dispatch --

    async def handle(self, parsed: ParsedInput) -> bool:
        """Dispatch a system-tier command. Returns True if handled."""
        cmd = parsed.command

        if cmd == "help":
            return self._handle_help()
        if cmd == "quit":
            raise KeyboardInterrupt
        if cmd == "agents":
            return await self._handle_agents()
        if cmd == "agent":
            return await self._handle_agent(parsed.command_args)
        if cmd == "reload":
            return await self._handle_reload()
        if cmd == "setup":
            return self._handle_setup(parsed.command_args)
        if cmd == "theme":
            return self._handle_theme(parsed.command_args)
        if cmd == "split":
            return self._handle_split(parsed.command_args)
        if cmd == "breakglass":
            return await self._handle_breakglass(parsed.command_args)
        if cmd == "models":
            return await self._handle_models()
        if cmd == "login":
            return await self._handle_login(parsed.command_args)
        return False

    # -- Individual handlers --

    def _handle_help(self) -> bool:
        commands_by_tier = {}
        for tier in (InputTier.SYSTEM, InputTier.SERVICE, InputTier.AGENT):
            commands = self.command_registry.commands_for_tier(tier)
            if commands:
                commands_by_tier[tier.value] = commands
        self.renderer.render_help(commands_by_tier)
        return True

    async def _handle_agents(self) -> bool:
        agents = await self.gateway.list_agents()
        if not agents:
            self.renderer.render_system("No agents available.")
        else:
            current = self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else ""
            self.renderer.render_agents_list(agents, current)
        return True

    async def _handle_agent(self, args: str | None) -> bool:
        if not args:
            self.renderer.render_error("Usage: /agent <name|new|edit>")
            return True
        agent_name = args.strip()

        if agent_name == "new":
            self.renderer.render_agent_new_template("config/agents")
            return True

        parts = agent_name.split(maxsplit=1)
        if parts[0] == "edit":
            edit_target = parts[1].strip() if len(parts) > 1 else ""
            await self._handle_agent_edit(edit_target)
            return True

        self.agent_stack.switch(agent_name, session_id="")
        self.renderer.render_system(f"Switched to @{agent_name}")
        return True

    async def _handle_agent_edit(self, agent_name: str) -> None:
        if not agent_name:
            self.renderer.render_error("Usage: /agent edit <name>")
            return

        agents = await self.gateway.list_agents()
        agent_ids = [a.get("id", "") for a in agents]
        if agent_name not in agent_ids:
            self.renderer.render_error(
                f"Agent '{agent_name}' not found. Available: {', '.join(agent_ids)}"
            )
            return

        config_path = f"config/agents/{agent_name}/agent.yaml"
        self.renderer.render_agent_edit_path(agent_name, config_path)

        if os.path.isfile(config_path):
            editor = os.environ.get("EDITOR", "")
            if editor:
                try:
                    subprocess.call([editor, config_path])
                    self.renderer.render_system(f"Returned from editor ({editor})")
                except FileNotFoundError:
                    self.renderer.render_system(
                        f"Editor '{editor}' not found. Edit the file manually: {config_path}"
                    )
                except OSError as exc:
                    self.renderer.render_system(f"Failed to launch editor: {exc}")
        else:
            self.renderer.render_system(
                f"Config file not found at {config_path}. "
                "Use /agent new to create a new agent."
            )

    async def _handle_reload(self) -> bool:
        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.parser.update_agents(agent_names)
        self.completer.update_agents(agent_names)
        self.renderer.render_system(
            f"Reloaded {len(agent_names)} agents: {', '.join(agent_names)}"
        )
        return True

    def _handle_setup(self, args: str | None) -> bool:
        providers = _get_credential_status()
        self.renderer.render_setup_dashboard(providers)
        return True

    def _handle_theme(self, args: str | None) -> bool:
        if not args or not args.strip():
            themes = available_themes()
            current = self.theme.name if self.theme else "default"
            self.renderer.render_system(f"Current theme: {current}")
            self.renderer.render_system(f"Available: {', '.join(themes)}")
            return True

        theme_name = args.strip()
        themes = available_themes()
        if theme_name not in themes:
            self.renderer.render_error(
                f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}"
            )
            return True

        # Theme switching requires rebuilding renderer + event handler.
        # We store the new theme and let the app handle the rebuild.
        self._pending_theme_switch = theme_name
        return True

    @property
    def pending_theme_switch(self) -> str | None:
        """If set, the app should rebuild renderer with this theme."""
        return getattr(self, "_pending_theme_switch", None)

    def clear_theme_switch(self) -> None:
        self._pending_theme_switch = None

    def _handle_split(self, args: str | None) -> bool:
        arg = (args or "").strip()

        if not arg:
            if self.split_manager.active:
                self.renderer.render_system(self.split_manager.display_label)
            else:
                self.renderer.render_system(
                    "Split mode is off. Usage: /split @agent1 @agent2"
                )
            return True

        if arg.lower() == "off":
            self.split_manager.deactivate()
            self.renderer.render_system("Split mode deactivated.")
            return True

        if arg.lower() == "swap":
            if not self.split_manager.active:
                self.renderer.render_error("Split mode is not active.")
                return True
            self.split_manager.swap()
            self.renderer.render_system(self.split_manager.display_label)
            return True

        tokens = arg.replace("@", "").split()
        if len(tokens) != 2:
            self.renderer.render_error(
                "Usage: /split @agent1 @agent2 | /split off | /split swap"
            )
            return True

        left, right = tokens
        self.split_manager.activate(left, right)
        self.renderer.render_system(f"Split mode activated: @{left} + @{right}")
        return True

    async def _handle_breakglass(self, args: str | None) -> bool:
        if args and args.strip().lower() == "off":
            self.deactivate_breakglass()
            return True

        if self.policy_engine is None:
            self.renderer.render_error(
                "No policy engine loaded. Cannot activate break-glass mode."
            )
            return True

        ttl_minutes = self._DEFAULT_BREAKGLASS_TTL_MINUTES
        if args and args.strip():
            try:
                ttl_minutes = int(args.strip())
            except ValueError:
                self.renderer.render_error(
                    f"Invalid TTL: '{args.strip()}'. Use a number of minutes or 'off'."
                )
                return True
            if ttl_minutes <= 0:
                self.renderer.render_error("TTL must be a positive number of minutes.")
                return True

        ttl_seconds = ttl_minutes * 60
        tier_cfg = self.policy_engine.tier_config("break_glass")
        max_ttl_seconds = tier_cfg.max_ttl if tier_cfg else 14400
        if ttl_seconds > max_ttl_seconds:
            ttl_seconds = max_ttl_seconds
            ttl_minutes = ttl_seconds // 60

        session_id = str(uuid.uuid4())
        token = create_break_glass_token(
            secret=self._break_glass_secret,
            agent_name="tui",
            session_id=session_id,
            ttl_seconds=ttl_seconds,
        )

        self._break_glass_token = token
        self._break_glass_expiry = time.time() + ttl_seconds
        self.permission_tier = "break_glass"
        self.status_bar.tier = "BREAK-GLASS"
        self.renderer.render_breakglass_activated(ttl_minutes)
        return True

    def deactivate_breakglass(self) -> None:
        """Deactivate break-glass mode — reset to default tier."""
        self._break_glass_token = None
        self._break_glass_expiry = None
        self.permission_tier = "default"
        self.status_bar.tier = None
        self.renderer.render_breakglass_deactivated()

    def check_breakglass_expiry(self) -> bool:
        """Check if break-glass has expired. Returns True if it just expired."""
        if (
            self._break_glass_expiry is not None
            and time.time() > self._break_glass_expiry
        ):
            self.deactivate_breakglass()
            self.renderer.render_system(
                "Break-glass mode expired — permissions reset to default."
            )
            return True
        return False

    async def _handle_login(self, args: str | None) -> bool:
        """Handle /login command for WebSocket authentication.

        If the gateway is not a WebSocketGateway, inform the user that login
        is not needed.  Otherwise, if a token is provided as an argument, use
        it directly.  If no argument, set a pending flag so the app prompts
        for token entry on the next input cycle.
        """
        if not isinstance(self.gateway, WebSocketGateway):
            self.renderer.render_system("Login not needed — using in-process gateway")
            return True

        token = (args or "").strip() if args else ""

        if not token:
            # No token provided — prompt user and set pending flag
            self._pending_login = True
            self.renderer.render_system("Enter session token:")
            return True

        # Token provided (either via args or pending completion)
        self.gateway.set_token(token)
        self.renderer.render_system("Token set. Reconnecting...")

        try:
            await self.gateway.disconnect()
            await self.gateway.connect()
            self.renderer.render_system("Reconnected successfully.")
        except Exception as exc:
            self.renderer.render_error(f"Reconnection failed: {exc}")

        return True

    @property
    def pending_login(self) -> bool:
        """If True, the app should treat the next input as a login token."""
        return self._pending_login

    def clear_pending_login(self) -> None:
        """Clear the pending login flag."""
        self._pending_login = False

    async def complete_login(self, token: str) -> None:
        """Complete a pending login with the provided token."""
        self._pending_login = False
        await self._handle_login(token)

    async def _handle_models(self) -> bool:
        models = await self.gateway.list_models()
        if not models:
            self.renderer.render_system("No models available.")
        else:
            for m in models:
                name = m.get("name", m.get("id", "unknown"))
                self.renderer.render_system(f"  {name}")
        return True


# ======================================================================
# Service command handlers
# ======================================================================


class ServiceCommandHandler:
    """Handles service-tier commands: tokens, sessions, memory, tools,
    view, edit, diff, export, audit, policy, workers, status, tool-history."""

    _AUDIT_DISPLAY_LIMIT: int = 20
    _OUTCOME_KEYWORDS: frozenset[str] = frozenset({"allowed", "denied", "failed"})

    def __init__(
        self,
        *,
        renderer: ChatRenderer,
        agent_stack: AgentStack,
        gateway: GatewayProtocol,
        token_counter: TokenCounter,
        session_manager: TuiSessionManager,
        audit_log: AuditLog | None,
        policy_engine_ref: "SystemCommandHandler",
    ) -> None:
        self.renderer = renderer
        self.agent_stack = agent_stack
        self.gateway = gateway
        self.token_counter = token_counter
        self.session_manager = session_manager
        self.audit_log = audit_log
        self._sys = policy_engine_ref  # For accessing policy_engine/permission_tier

    # -- Dispatch --

    async def handle(self, parsed: ParsedInput) -> bool:
        """Dispatch a service-tier command. Returns True if handled."""
        cmd = parsed.command

        if cmd == "tokens":
            return self._handle_tokens()
        if cmd == "sessions":
            return await self._handle_sessions(parsed.command_args)
        if cmd == "session":
            return await self._handle_session(parsed.command_args)
        if cmd == "memory":
            return await self._handle_memory(parsed.command_args or "")
        if cmd == "tools":
            return await self._handle_tools()
        if cmd == "tool":
            return await self._handle_tool(parsed.command_args)
        if cmd == "view":
            return self._handle_view(parsed.command_args or "")
        if cmd == "edit":
            return self._handle_edit(parsed.command_args or "")
        if cmd == "diff":
            return self._handle_diff(parsed.command_args or "")
        if cmd == "export":
            await self._handle_export(parsed.command_args)
            return True
        if cmd == "audit":
            return self._handle_audit(parsed.command_args)
        if cmd == "policy":
            return self._handle_policy()
        if cmd == "workers":
            return self._handle_workers()
        if cmd == "status":
            return await self._handle_status()
        if cmd == "tool-history":
            return self._handle_tool_history()

        self.renderer.render_system(f"/{cmd} — not yet implemented")
        return True

    # -- Individual handlers --

    def _current_agent(self) -> str:
        return self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else "huginn"

    def _handle_tokens(self) -> bool:
        self.renderer.render_system(f"Session total: {self.token_counter.format_display()}")
        for agent, count in self.token_counter.all_agents.items():
            self.renderer.render_system(f"  @{agent}: {count:,} tokens")
        return True

    async def _handle_sessions(self, args: str | None) -> bool:
        args_str = (args or "").strip()
        sessions = await self.session_manager.list_sessions()

        if args_str.startswith("search "):
            query = args_str[7:].strip().strip('"').strip("'")
            if query:
                sessions = [
                    s for s in sessions
                    if query.lower() in (s.summary or "").lower()
                    or query.lower() in (s.agent_name or "").lower()
                ]
                self.renderer.render_sessions_table(sessions, title=f"Sessions matching '{query}'")
            else:
                self.renderer.render_error('Usage: /sessions search "query"')
        else:
            self.renderer.render_sessions_table(sessions)
        return True

    async def _handle_session(self, args: str | None) -> bool:
        parts = (args or "").strip().split(maxsplit=1)
        if not parts:
            self.renderer.render_error("Usage: /session new | /session resume <id>")
            return True
        action = parts[0]
        if action == "new":
            agent = self._current_agent()
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

    async def _handle_memory(self, args: str) -> bool:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            self.renderer.render_error("Usage: /memory search <query> | list | save <text> | forget <id>")
            return True

        action = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        agent = self._current_agent()

        if action == "search":
            if not rest:
                self.renderer.render_error("Usage: /memory search <query>")
                return True
            try:
                results = await self.gateway.memory_search(rest, agent)
                self.renderer.render_memory_results(results, title=f"Memory Search: {rest}")
            except Exception as exc:
                self.renderer.render_error(f"Memory search failed: {exc}")
            return True

        if action == "list":
            try:
                results = await self.gateway.memory_list(agent)
                self.renderer.render_memory_results(results, title="Recent Memories")
            except Exception as exc:
                self.renderer.render_error(f"Memory list failed: {exc}")
            return True

        if action == "save":
            if not rest:
                self.renderer.render_error("Usage: /memory save <text>")
                return True
            try:
                record_id = await self.gateway.memory_save(rest, agent)
                self.renderer.render_system(f"Memory saved: {record_id[:8]}")
            except Exception as exc:
                self.renderer.render_error(f"Memory save failed: {exc}")
            return True

        if action == "forget":
            if not rest:
                self.renderer.render_error("Usage: /memory forget <id>")
                return True
            try:
                ok = await self.gateway.memory_forget(rest.strip(), agent)
                if ok:
                    self.renderer.render_system(f"Memory forgotten: {rest.strip()[:8]}")
                else:
                    self.renderer.render_error(f"Memory not found: {rest.strip()[:8]}")
            except Exception as exc:
                self.renderer.render_error(f"Memory forget failed: {exc}")
            return True

        self.renderer.render_error("Usage: /memory search <query> | list | save <text> | forget <id>")
        return True

    async def _handle_tools(self) -> bool:
        agent = self._current_agent()
        try:
            tools = await self.gateway.list_agent_tools(agent)
            self.renderer.render_tools_list(tools, agent)
        except Exception as exc:
            self.renderer.render_error(f"Failed to list tools: {exc}")
        return True

    async def _handle_tool(self, args: str | None) -> bool:
        tool_name = (args or "").strip()
        if not tool_name:
            self.renderer.render_error("Usage: /tool <name>")
            return True
        agent = self._current_agent()
        try:
            tools = await self.gateway.list_agent_tools(agent)
            matching = [t for t in tools if t.get("name") == tool_name]
            if matching:
                self.renderer.render_tool_detail(matching[0], agent)
            else:
                self.renderer.render_error(f"Tool '{tool_name}' not found for @{agent}")
        except Exception as exc:
            self.renderer.render_error(f"Failed to get tool details: {exc}")
        return True

    def _handle_view(self, args: str) -> bool:
        path = args.strip()
        if not path:
            self.renderer.render_error("Usage: /view <path>")
            return True

        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)

        try:
            with open(path) as f:
                content = f.read()
        except FileNotFoundError:
            self.renderer.render_error(f"File not found: {path}")
            return True
        except PermissionError:
            self.renderer.render_error(f"Permission denied: {path}")
            return True
        except OSError as exc:
            self.renderer.render_error(f"Cannot read file: {exc}")
            return True

        language = _detect_language(path)
        self.renderer.render_file_view(path, content, language)
        return True

    def _handle_edit(self, args: str) -> bool:
        path = args.strip()
        if not path:
            self.renderer.render_error("Usage: /edit <path>")
            return True

        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)

        editor = os.environ.get("EDITOR", "vim")
        try:
            subprocess.call([editor, path])
            self.renderer.render_system(f"Returned from editor ({editor})")
        except FileNotFoundError:
            self.renderer.render_error(f"Editor not found: {editor}")
        except OSError as exc:
            self.renderer.render_error(f"Failed to launch editor: {exc}")
        return True

    def _handle_diff(self, args: str) -> bool:
        path = args.strip()
        cmd = ["git", "diff"]
        if path:
            path = os.path.expanduser(path)
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            cmd.append(path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            diff_text = result.stdout
        except FileNotFoundError:
            self.renderer.render_error("git not found on PATH")
            return True
        except subprocess.TimeoutExpired:
            self.renderer.render_error("git diff timed out")
            return True
        except OSError as exc:
            self.renderer.render_error(f"Failed to run git diff: {exc}")
            return True

        self.renderer.render_diff(diff_text, path=path)
        return True

    async def _handle_export(self, args: str | None) -> None:
        session_id = self.session_manager.current_session_id
        if not session_id:
            self.renderer.render_system("Nothing to export — no active session.")
            return

        try:
            detail = await self.gateway.resume_session(session_id)
        except Exception as exc:
            self.renderer.render_error(f"Failed to load session: {exc}")
            return

        messages = detail.messages
        if not messages:
            self.renderer.render_system("Nothing to export — session has no messages.")
            return

        if args and args.strip():
            dest = Path(os.path.expanduser(args.strip()))
            if not dest.is_absolute():
                dest = Path.cwd() / dest
        else:
            dest = default_export_path()

        try:
            export_session_to_markdown(messages, dest)
            self.renderer.render_system(f"Session exported to {dest}")
        except OSError as exc:
            self.renderer.render_error(f"Failed to write export: {exc}")

    def _handle_audit(self, args: str | None) -> bool:
        if self.audit_log is None:
            self.renderer.render_error("Audit log not configured.")
            return True

        filter_arg = (args or "").strip().lower() or None

        if filter_arg and filter_arg in self._OUTCOME_KEYWORDS:
            entries = self.audit_log.read_entries()
            entry_dicts = [asdict(e) for e in entries if e.outcome == filter_arg]
            title = f"Audit Log — outcome: {filter_arg}"
        elif filter_arg:
            entries = self.audit_log.read_entries(agent_name=filter_arg)
            entry_dicts = [asdict(e) for e in entries]
            title = f"Audit Log — agent: {filter_arg}"
        else:
            entries = self.audit_log.read_entries()
            entry_dicts = [asdict(e) for e in entries]
            title = "Audit Log"

        if len(entry_dicts) > self._AUDIT_DISPLAY_LIMIT:
            entry_dicts = entry_dicts[-self._AUDIT_DISPLAY_LIMIT:]
            title += f" (last {self._AUDIT_DISPLAY_LIMIT})"

        self.renderer.render_audit_entries(entry_dicts, title=title)
        return True

    def _handle_policy(self) -> bool:
        if self._sys.policy_engine is None:
            self.renderer.render_system("No policy loaded. Place a policy.yaml in config/ and restart.")
        else:
            self.renderer.render_policy(self._sys.policy_engine, self._sys.permission_tier)
        return True

    def _handle_workers(self) -> bool:
        if self.agent_stack.depth == 0:
            self.renderer.render_system("No active agents.")
            return True

        current = self.agent_stack.current
        children = current.children if current.children else []
        if not children:
            self.renderer.render_system(f"@{current.agent_name} has no active workers.")
            return True

        self.renderer.render_system(f"Workers for @{current.agent_name}:")
        for child in children:
            status_label = child.status.value if hasattr(child.status, "value") else str(child.status)
            self.renderer.render_system(f"  @{child.agent_name} [{status_label}]")
        return True

    async def _handle_status(self) -> bool:
        lines = []

        connected = hasattr(self.gateway, "_connected") and self.gateway._connected
        lines.append(f"Gateway: {'connected' if connected else 'not connected'}")

        try:
            agents = await self.gateway.list_agents()
            lines.append(f"Agents: {len(agents)} available")
        except Exception:
            lines.append("Agents: unavailable")

        if self.agent_stack.depth > 0:
            lines.append(f"Current: @{self.agent_stack.current.agent_name}")

        lines.append(f"Tokens: {self.token_counter.format_display()}")
        lines.append(f"Permission tier: {self._sys.permission_tier}")

        if self._sys._break_glass_token is not None and self._sys._break_glass_expiry is not None:
            remaining = max(0, self._sys._break_glass_expiry - time.time())
            mins = int(remaining // 60)
            lines.append(f"Break-glass: active ({mins}m remaining)")

        for line in lines:
            self.renderer.render_system(line)
        return True

    def _handle_tool_history(self) -> bool:
        if self.audit_log is None:
            self.renderer.render_error("Audit log not configured — cannot show tool history.")
            return True

        entries = self.audit_log.read_entries()
        if not entries:
            self.renderer.render_system("No tool calls recorded.")
            return True

        entry_dicts = [asdict(e) for e in entries[-20:]]
        self.renderer.render_audit_entries(entry_dicts, title="Tool History")
        return True


# ======================================================================
# Helper functions (no class state needed)
# ======================================================================


def _detect_language(path: str) -> str:
    """Detect language from file extension for syntax highlighting."""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".md": "markdown", ".html": "html",
        ".css": "css", ".sh": "bash", ".bash": "bash",
        ".rs": "rust", ".go": "go", ".java": "java",
        ".rb": "ruby", ".sql": "sql", ".xml": "xml",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
        ".svelte": "html", ".tsx": "tsx", ".jsx": "jsx",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return "text"


def _get_credential_status() -> list[dict]:
    """Check environment variables for each provider and return status list."""
    providers: list[dict] = []

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    providers.append({
        "name": "Anthropic",
        "configured": bool(anthropic_key),
        "detail": "ANTHROPIC_API_KEY set" if anthropic_key else "ANTHROPIC_API_KEY missing",
    })

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    providers.append({
        "name": "OpenAI",
        "configured": bool(openai_key),
        "detail": "OPENAI_API_KEY set" if openai_key else "OPENAI_API_KEY missing",
    })

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    providers.append({
        "name": "Ollama",
        "configured": True,
        "detail": ollama_host,
    })

    gmail_creds = os.environ.get("GMAIL_CREDENTIALS", "")
    google_client = os.environ.get("GOOGLE_CLIENT_ID", "")
    gmail_configured = bool(gmail_creds or google_client)
    if gmail_creds:
        gmail_detail = "GMAIL_CREDENTIALS set"
    elif google_client:
        gmail_detail = "GOOGLE_CLIENT_ID set"
    else:
        gmail_detail = "GMAIL_CREDENTIALS or GOOGLE_CLIENT_ID missing"
    providers.append({
        "name": "Gmail",
        "configured": gmail_configured,
        "detail": gmail_detail,
    })

    ha_token = os.environ.get("HA_TOKEN", "")
    ha_url = os.environ.get("HA_URL", "")
    ha_configured = bool(ha_token or ha_url)
    if ha_token:
        ha_detail = "HA_TOKEN set"
    elif ha_url:
        ha_detail = f"HA_URL: {ha_url}"
    else:
        ha_detail = "HA_TOKEN or HA_URL missing"
    providers.append({
        "name": "Home Assistant",
        "configured": ha_configured,
        "detail": ha_detail,
    })

    paperless_token = os.environ.get("PAPERLESS_TOKEN", "")
    paperless_url = os.environ.get("PAPERLESS_URL", "")
    paperless_configured = bool(paperless_token or paperless_url)
    if paperless_token:
        paperless_detail = "PAPERLESS_TOKEN set"
    elif paperless_url:
        paperless_detail = f"PAPERLESS_URL: {paperless_url}"
    else:
        paperless_detail = "PAPERLESS_TOKEN or PAPERLESS_URL missing"
    providers.append({
        "name": "Paperless",
        "configured": paperless_configured,
        "detail": paperless_detail,
    })

    firefly_token = os.environ.get("FIREFLY_TOKEN", "")
    firefly_url = os.environ.get("FIREFLY_URL", "")
    firefly_configured = bool(firefly_token or firefly_url)
    if firefly_token:
        firefly_detail = "FIREFLY_TOKEN set"
    elif firefly_url:
        firefly_detail = f"FIREFLY_URL: {firefly_url}"
    else:
        firefly_detail = "FIREFLY_TOKEN or FIREFLY_URL missing"
    providers.append({
        "name": "Firefly",
        "configured": firefly_configured,
        "detail": firefly_detail,
    })

    return providers
