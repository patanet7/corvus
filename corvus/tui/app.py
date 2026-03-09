"""Corvus TUI main application — chat loop and command dispatch."""

import asyncio
import json
import logging
import os
import secrets
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console

load_dotenv()

from corvus.security.audit import AuditLog
from corvus.security.policy import PolicyEngine
from corvus.security.tokens import create_break_glass_token
from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.core.exporter import default_export_path, export_session_to_markdown
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.core.split_manager import SplitManager
from corvus.tui.input.completer import ChatCompleter
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
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
        self.status_bar = StatusBar(self.agent_stack, self.token_counter, self.theme)
        self.session_manager = TuiSessionManager(self.gateway, self.agent_stack)
        self._always_allow: set[str] = set()
        self.split_manager = SplitManager()

        # Policy engine and permission tier
        self.policy_engine: PolicyEngine | None = None
        self.permission_tier: str = "default"

        # Break-glass state
        self._break_glass_token: str | None = None
        self._break_glass_expiry: float | None = None
        self._break_glass_secret: bytes = secrets.token_bytes(32)

        # Audit log — initialised from CORVUS_AUDIT_LOG env var or default path
        audit_path = os.environ.get("CORVUS_AUDIT_LOG", "logs/audit.jsonl")
        self._audit_log: AuditLog | None = AuditLog(Path(audit_path)) if audit_path else None

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
        """Build the prompt with agent path (token count is in the status bar)."""
        if self.agent_stack.depth == 0:
            return HTML("<b>corvus</b>&gt; ")

        agent = self.agent_stack.current.agent_name
        if self.agent_stack.depth == 1:
            return HTML(f"<b>@{agent}</b>&gt; ")

        breadcrumb = self.agent_stack.breadcrumb
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
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_system_command(self, parsed: ParsedInput) -> bool:
        """Handle system-tier commands. Returns True if handled."""
        cmd_name = parsed.command

        if cmd_name == "help":
            commands_by_tier = {}
            for tier in (InputTier.SYSTEM, InputTier.SERVICE, InputTier.AGENT):
                commands = self.command_registry.commands_for_tier(tier)
                if commands:
                    commands_by_tier[tier.value] = commands
            self.renderer.render_help(commands_by_tier)
            return True

        if cmd_name == "quit":
            raise KeyboardInterrupt

        if cmd_name == "agents":
            agents = await self.gateway.list_agents()
            if not agents:
                self.renderer.render_system("No agents available.")
            else:
                current = self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else ""
                self.renderer.render_agents_list(agents, current)
            return True

        if cmd_name == "agent":
            agent_name = parsed.command_args
            if not agent_name:
                self.renderer.render_error("Usage: /agent <name|new|edit>")
                return True
            agent_name = agent_name.strip()

            # Sub-commands: /agent new, /agent edit <name>
            if agent_name == "new":
                await self._handle_agent_new_command()
                return True

            parts = agent_name.split(maxsplit=1)
            if parts[0] == "edit":
                edit_target = parts[1].strip() if len(parts) > 1 else ""
                await self._handle_agent_edit_command(edit_target)
                return True

            # Default: switch to agent
            self.agent_stack.switch(agent_name, session_id="")
            self.renderer.render_system(f"Switched to @{agent_name}")
            return True

        if cmd_name == "reload":
            await self._handle_reload_command()
            return True

        if cmd_name == "setup":
            self._handle_setup_command(parsed.command_args)
            return True

        if cmd_name == "theme":
            self._handle_theme_command(parsed.command_args)
            return True

        if cmd_name == "split":
            self._handle_split_command(parsed.command_args)
            return True

        if cmd_name == "breakglass":
            await self._handle_breakglass_command(parsed.command_args)
            return True

        if cmd_name == "models":
            models = await self.gateway.list_models()
            if not models:
                self.renderer.render_system("No models available.")
            else:
                for m in models:
                    name = m.get("name", m.get("id", "unknown"))
                    self.renderer.render_system(f"  {name}")
            return True

        return False

    # ------------------------------------------------------------------
    # Agent management commands
    # ------------------------------------------------------------------

    async def _handle_agent_new_command(self) -> None:
        """Handle '/agent new' — show YAML config template and config path."""
        config_dir = "config/agents"
        self.renderer.render_agent_new_template(config_dir)

    async def _handle_agent_edit_command(self, agent_name: str) -> None:
        """Handle '/agent edit <name>' — show config path or open in editor."""
        if not agent_name:
            self.renderer.render_error("Usage: /agent edit <name>")
            return

        # Check if agent exists in gateway
        agents = await self.gateway.list_agents()
        agent_ids = [a.get("id", "") for a in agents]
        if agent_name not in agent_ids:
            self.renderer.render_error(
                f"Agent '{agent_name}' not found. "
                f"Available: {', '.join(agent_ids)}"
            )
            return

        config_path = f"config/agents/{agent_name}/agent.yaml"
        self.renderer.render_agent_edit_path(agent_name, config_path)

        # Attempt to open in $EDITOR if available
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

    async def _handle_reload_command(self) -> None:
        """Handle '/reload' — re-fetch agents and update parser/completer."""
        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.parser.update_agents(agent_names)
        self.completer.update_agents(agent_names)
        self.renderer.render_system(
            f"Reloaded {len(agent_names)} agents: {', '.join(agent_names)}"
        )

    def _get_credential_status(self) -> list[dict]:
        """Check environment variables for each provider and return status list.

        Returns:
            List of dicts with keys: name (str), configured (bool), detail (str).
        """
        providers: list[dict] = []

        # Anthropic
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        providers.append({
            "name": "Anthropic",
            "configured": bool(anthropic_key),
            "detail": "ANTHROPIC_API_KEY set" if anthropic_key else "ANTHROPIC_API_KEY missing",
        })

        # OpenAI
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        providers.append({
            "name": "OpenAI",
            "configured": bool(openai_key),
            "detail": "OPENAI_API_KEY set" if openai_key else "OPENAI_API_KEY missing",
        })

        # Ollama (defaults to localhost)
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        providers.append({
            "name": "Ollama",
            "configured": True,
            "detail": ollama_host,
        })

        # Gmail
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

        # Home Assistant
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

        # Paperless
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

        # Firefly
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

    def _handle_setup_command(self, args: str | None) -> None:
        """Handle '/setup' and '/setup status' — render credential dashboard.

        Args:
            args: Optional sub-command. 'status' or None both show the dashboard.
        """
        providers = self._get_credential_status()
        self.renderer.render_setup_dashboard(providers)

    def _handle_theme_command(self, args: str | None) -> None:
        """Handle '/theme [name]' — switch theme or list available themes."""
        from corvus.tui.theme import TuiTheme, available_themes

        if not args or not args.strip():
            themes = available_themes()
            current = self.theme.name
            self.renderer.render_system(f"Current theme: {current}")
            self.renderer.render_system(f"Available: {', '.join(themes)}")
            return

        theme_name = args.strip()
        themes = available_themes()
        if theme_name not in themes:
            self.renderer.render_error(f"Unknown theme '{theme_name}'. Available: {', '.join(themes)}")
            return

        self.theme = TuiTheme(theme_name)
        self.renderer = ChatRenderer(self.console, self.theme)
        self.event_handler = EventHandler(self.renderer, self.agent_stack, self.token_counter)
        self.status_bar = StatusBar(self.agent_stack, self.token_counter, self.theme)
        self.renderer.render_system(f"Theme switched to '{theme_name}'")

    async def _handle_service_command(self, parsed: ParsedInput) -> bool:
        """Handle service-tier commands. Returns True if handled."""
        cmd_name = parsed.command

        if cmd_name == "tokens":
            self.renderer.render_system(f"Session total: {self.token_counter.format_display()}")
            for agent, count in self.token_counter.all_agents.items():
                self.renderer.render_system(f"  @{agent}: {count:,} tokens")
            return True

        if cmd_name == "sessions":
            args = (parsed.command_args or "").strip()
            sessions = await self.session_manager.list_sessions()
            # /sessions search "query" — filter sessions
            if args.startswith("search "):
                query = args[7:].strip().strip('"').strip("'")
                if query:
                    sessions = [
                        s for s in sessions
                        if query.lower() in (s.summary or "").lower()
                        or query.lower() in (s.agent_name or "").lower()
                    ]
                    self.renderer.render_sessions_table(sessions, title=f"Sessions matching '{query}'")
                else:
                    self.renderer.render_error("Usage: /sessions search \"query\"")
            else:
                self.renderer.render_sessions_table(sessions)
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

        if cmd_name == "memory":
            return await self._handle_memory_command(parsed.command_args or "")

        if cmd_name == "tools":
            agent = self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else "huginn"
            try:
                tools = await self.gateway.list_agent_tools(agent)
                self.renderer.render_tools_list(tools, agent)
            except Exception as exc:
                self.renderer.render_error(f"Failed to list tools: {exc}")
            return True

        if cmd_name == "tool":
            tool_name = (parsed.command_args or "").strip()
            if not tool_name:
                self.renderer.render_error("Usage: /tool <name>")
                return True
            agent = self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else "huginn"
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

        if cmd_name == "view":
            return self._handle_view_command(parsed.command_args or "")

        if cmd_name == "edit":
            return self._handle_edit_command(parsed.command_args or "")

        if cmd_name == "diff":
            return self._handle_diff_command(parsed.command_args or "")

        if cmd_name == "export":
            await self._handle_export_command(parsed.command_args)
            return True

        if cmd_name == "audit":
            self._handle_audit_command(parsed.command_args)
            return True

        if cmd_name == "policy":
            await self._handle_policy_command()
            return True

        self.renderer.render_system(f"/{cmd_name} — not yet implemented")
        return True

    # ------------------------------------------------------------------
    # Policy command
    # ------------------------------------------------------------------

    async def _handle_policy_command(self) -> None:
        """Handle /policy — display current security policy state."""
        if self.policy_engine is None:
            self.renderer.render_system("No policy loaded. Place a policy.yaml in config/ and restart.")
            return
        self.renderer.render_policy(self.policy_engine, self.permission_tier)

    # ------------------------------------------------------------------
    # Split mode command
    # ------------------------------------------------------------------

    def _handle_split_command(self, args: str | None) -> None:
        """Handle /split — toggle or configure split mode.

        Usage:
            /split @agent1 @agent2   — activate split with two agents
            /split off               — deactivate split mode
            /split swap              — swap left and right panes
            /split                   — show current split status
        """
        arg = (args or "").strip()

        if not arg:
            if self.split_manager.active:
                self.renderer.render_system(self.split_manager.display_label)
            else:
                self.renderer.render_system(
                    "Split mode is off. Usage: /split @agent1 @agent2"
                )
            return

        if arg.lower() == "off":
            self.split_manager.deactivate()
            self.renderer.render_system("Split mode deactivated.")
            return

        if arg.lower() == "swap":
            if not self.split_manager.active:
                self.renderer.render_error("Split mode is not active.")
                return
            self.split_manager.swap()
            self.renderer.render_system(self.split_manager.display_label)
            return

        # Parse two agent names: /split @homelab @finance or /split homelab finance
        tokens = arg.replace("@", "").split()
        if len(tokens) != 2:
            self.renderer.render_error(
                "Usage: /split @agent1 @agent2 | /split off | /split swap"
            )
            return

        left, right = tokens
        self.split_manager.activate(left, right)
        self.renderer.render_system(
            f"Split mode activated: @{left} + @{right}"
        )

    # ------------------------------------------------------------------
    # Break-glass command
    # ------------------------------------------------------------------

    _DEFAULT_BREAKGLASS_TTL_MINUTES: int = 60

    async def _handle_breakglass_command(self, args: str | None) -> None:
        """Handle /breakglass [ttl_minutes|off] — activate or deactivate break-glass mode.

        Args:
            args: Optional argument string. 'off' deactivates. A number sets TTL
                  in minutes. None uses the default (60 minutes).
        """
        # Deactivation
        if args and args.strip().lower() == "off":
            self._deactivate_breakglass()
            return

        # Require policy engine
        if self.policy_engine is None:
            self.renderer.render_error(
                "No policy engine loaded. Cannot activate break-glass mode."
            )
            return

        # Parse TTL
        ttl_minutes = self._DEFAULT_BREAKGLASS_TTL_MINUTES
        if args and args.strip():
            try:
                ttl_minutes = int(args.strip())
            except ValueError:
                self.renderer.render_error(
                    f"Invalid TTL: '{args.strip()}'. Use a number of minutes or 'off'."
                )
                return
            if ttl_minutes <= 0:
                self.renderer.render_error("TTL must be a positive number of minutes.")
                return

        # Clamp to policy max_ttl
        ttl_seconds = ttl_minutes * 60
        tier_cfg = self.policy_engine.tier_config("break_glass")
        max_ttl_seconds = tier_cfg.max_ttl if tier_cfg else 14400
        if ttl_seconds > max_ttl_seconds:
            ttl_seconds = max_ttl_seconds
            ttl_minutes = ttl_seconds // 60

        # Generate session ID for the token
        session_id = str(uuid.uuid4())

        # Create token
        token = create_break_glass_token(
            secret=self._break_glass_secret,
            agent_name="tui",
            session_id=session_id,
            ttl_seconds=ttl_seconds,
        )

        # Activate
        self._break_glass_token = token
        self._break_glass_expiry = time.time() + ttl_seconds
        self.permission_tier = "break_glass"
        self.status_bar.tier = "BREAK-GLASS"

        self.renderer.render_breakglass_activated(ttl_minutes)

    def _deactivate_breakglass(self) -> None:
        """Deactivate break-glass mode — reset to default tier."""
        self._break_glass_token = None
        self._break_glass_expiry = None
        self.permission_tier = "default"
        self.status_bar.tier = None

        self.renderer.render_breakglass_deactivated()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    _AUDIT_DISPLAY_LIMIT: int = 20
    _OUTCOME_KEYWORDS: frozenset[str] = frozenset({"allowed", "denied", "failed"})

    def _handle_audit_command(self, args: str | None) -> None:
        """Handle /audit [agent|outcome] — display recent audit entries.

        Args:
            args: Optional filter string. If it matches a known outcome
                  keyword (allowed/denied/failed) entries are filtered by
                  outcome. Otherwise it is treated as an agent name filter.
                  None or empty shows the last 20 entries unfiltered.
        """
        if self._audit_log is None:
            self.renderer.render_error("Audit log not configured.")
            return

        filter_arg = (args or "").strip().lower() or None

        # Determine filter strategy
        if filter_arg and filter_arg in self._OUTCOME_KEYWORDS:
            # Outcome filter: read all entries, then post-filter
            entries = self._audit_log.read_entries()
            entry_dicts = [asdict(e) for e in entries if e.outcome == filter_arg]
            title = f"Audit Log — outcome: {filter_arg}"
        elif filter_arg:
            # Agent name filter: use AuditLog's built-in filter
            entries = self._audit_log.read_entries(agent_name=filter_arg)
            entry_dicts = [asdict(e) for e in entries]
            title = f"Audit Log — agent: {filter_arg}"
        else:
            # No filter: show last N entries
            entries = self._audit_log.read_entries()
            entry_dicts = [asdict(e) for e in entries]
            title = "Audit Log"

        # Limit to last N entries
        if len(entry_dicts) > self._AUDIT_DISPLAY_LIMIT:
            entry_dicts = entry_dicts[-self._AUDIT_DISPLAY_LIMIT:]
            title += f" (last {self._AUDIT_DISPLAY_LIMIT})"

        self.renderer.render_audit_entries(entry_dicts, title=title)

    # ------------------------------------------------------------------
    # Memory sub-commands
    # ------------------------------------------------------------------

    async def _handle_memory_command(self, args: str) -> bool:
        """Handle /memory sub-commands: search, list, save, forget."""
        parts = args.strip().split(maxsplit=1)
        if not parts:
            self.renderer.render_error("Usage: /memory search <query> | list | save <text> | forget <id>")
            return True

        action = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        agent = self.agent_stack.current.agent_name if self.agent_stack.depth > 0 else "huginn"

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

    # ------------------------------------------------------------------
    # File operations (local, no gateway needed)
    # ------------------------------------------------------------------

    @staticmethod
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

    def _handle_view_command(self, args: str) -> bool:
        """Handle /view <path> — read and display a file with syntax highlighting."""
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

        language = self._detect_language(path)
        self.renderer.render_file_view(path, content, language)
        return True

    def _handle_edit_command(self, args: str) -> bool:
        """Handle /edit <path> — open file in $EDITOR."""
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

    def _handle_diff_command(self, args: str) -> bool:
        """Handle /diff [path] — run git diff and display with syntax highlighting."""
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

    # ------------------------------------------------------------------
    # Export command
    # ------------------------------------------------------------------

    async def _handle_export_command(self, args: str | None) -> None:
        """Handle /export [path] — export current session to markdown.

        If no path is given, defaults to ~/corvus-export-YYYY-MM-DD.md.
        Fetches the current session's messages and writes them as formatted
        markdown.
        """
        # Determine the current session
        session_id = self.session_manager.current_session_id
        if not session_id:
            self.renderer.render_system("Nothing to export — no active session.")
            return

        # Fetch session messages
        try:
            detail = await self.gateway.resume_session(session_id)
        except Exception as exc:
            self.renderer.render_error(f"Failed to load session: {exc}")
            return

        messages = detail.messages
        if not messages:
            self.renderer.render_system("Nothing to export — session has no messages.")
            return

        # Determine export path
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

    # ------------------------------------------------------------------
    # Agent input handling
    # ------------------------------------------------------------------

    async def _handle_agent_input(self, parsed: ParsedInput) -> None:
        """Handle agent-tier input: chat, mentions, tool calls, and agent commands."""
        if not parsed.text.strip():
            return
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
        session: PromptSession = PromptSession(completer=self.completer)

        self.renderer.render_system("Connecting to Corvus gateway...")
        await self.gateway.connect()
        self.gateway.on_event(self.event_handler.handle)

        # Wire auto-approve for always-allowed tools
        def _auto_approve_confirm(tool_id: str, _action: str) -> None:
            import asyncio as _asyncio
            try:
                loop = _asyncio.get_running_loop()
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
                try:
                    prompt = self._build_prompt()
                    raw = await session.prompt_async(prompt, bottom_toolbar=self.status_bar)
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
    import argparse
    import os

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
    logging.basicConfig(
        filename="logs/tui.log",
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app = TuiApp()

    if args.mode == "websocket":
        from corvus.tui.protocol.websocket import WebSocketGateway
        app.gateway = WebSocketGateway(url=args.url, token=args.token)
        app.session_manager = TuiSessionManager(app.gateway, app.agent_stack)

    asyncio.run(app.run())
