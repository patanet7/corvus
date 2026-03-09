"""Rich-based chat renderer for the Corvus TUI."""

import json
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from corvus.security.policy import PolicyEngine
from corvus.security.sanitizer import sanitize_tool_result
from corvus.tui.theme import TuiTheme

_TOOL_RESULT_MAX = 500


class ChatRenderer:
    """Renders chat messages, tool calls, and UI chrome to a Rich Console."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        self._console = console
        self._theme = theme
        self._live: Live | None = None
        self._stream_buffer: list[str] = []
        self._stream_agent: str = ""
        self._thinking_live: Live | None = None

    # -- Welcome --

    def render_welcome(self, agent_count: int, default_agent: str) -> None:
        """Display the CORVUS welcome banner with agent count and hints."""
        banner = Text()
        banner.append("CORVUS", style="bold cyan")
        banner.append(f" — {agent_count} agents ready\n", style=self._theme.muted)
        banner.append(f"  Default: @{default_agent}\n", style=self._theme.muted)
        banner.append("  /help for commands, /quit to exit", style=self._theme.muted)
        panel = Panel(banner, border_style=self._theme.border, expand=False)
        self._console.print(panel)

    # -- User / agent messages --

    def render_user_message(self, text: str, agent: str) -> None:
        """Display a user message with 'You → @agent:' label."""
        label = Text(f"You → @{agent}: ", style=self._theme.user_label)
        label.append(text)
        self._console.print(label)

    def render_agent_message(self, agent: str, text: str, tokens: int = 0) -> None:
        """Display an agent response with the agent name in its color."""
        color = self._theme.agent_color(agent)
        header = Text(f"@{agent}: ", style=f"bold {color}")
        self._console.print(header)
        self._console.print(Markdown(text))
        if tokens:
            self._console.print(
                Text(f"  [{tokens:,} tokens]", style=self._theme.muted)
            )

    # -- Thinking spinner --

    def render_thinking_start(self, agent: str) -> None:
        """Show a spinner while the agent is thinking."""
        self._stop_thinking()
        color = self._theme.agent_color(agent)
        spinner = Spinner("dots", text=Text(f" @{agent} thinking…", style=f"bold {color}"))
        self._thinking_live = Live(spinner, console=self._console, transient=True)
        self._thinking_live.start()

    def _stop_thinking(self) -> None:
        """Stop the thinking spinner if active."""
        if self._thinking_live is not None:
            self._thinking_live.stop()
            self._thinking_live = None

    # -- Streaming --

    def _build_stream_panel(self, agent: str, color: str, content: str) -> Panel:
        """Build a panel for the current streaming state."""
        return Panel(
            Markdown(content) if content else Text("…"),
            title=f"[bold {color}]@{agent}[/]",
            border_style=color,
            expand=False,
        )

    def render_stream_start(self, agent: str) -> None:
        """Start a Live streaming panel for agent output."""
        self._stop_thinking()
        color = self._theme.agent_color(agent)
        self._stream_agent = agent
        self._stream_buffer = []
        self._live = Live(
            self._build_stream_panel(agent, color, ""),
            console=self._console,
            refresh_per_second=8,
            transient=True,
            vertical_overflow="visible",
        )
        self._live.start()

    def render_stream_chunk(self, chunk: str) -> None:
        """Append a chunk to the streaming buffer and update the Live display."""
        self._stream_buffer.append(chunk)
        if self._live is not None:
            color = self._theme.agent_color(self._stream_agent)
            content = "".join(self._stream_buffer)
            self._live.update(self._build_stream_panel(self._stream_agent, color, content))

    def render_stream_end(self, tokens: int = 0) -> None:
        """Finish a streamed response — render final panel."""
        if self._live is not None:
            self._live.stop()
            self._live = None

        content = "".join(self._stream_buffer).strip()
        agent = self._stream_agent

        # Reset state
        self._stream_buffer = []
        self._stream_agent = ""

        if not content:
            return

        color = self._theme.agent_color(agent)
        header = Text(f"@{agent}: ", style=f"bold {color}")
        self._console.print(header)
        self._console.print(Markdown(content))
        if tokens:
            self._console.print(
                Text(f"  [{tokens:,} tokens]", style=self._theme.muted)
            )

    # -- Tool calls --

    def render_tool_start(self, tool_name: str, params: dict, agent: str) -> None:
        """Show a panel indicating a tool call is starting."""
        self._stop_thinking()
        color = self._theme.agent_color(agent)
        try:
            body = json.dumps(params, indent=2, default=str)
        except (TypeError, ValueError):
            body = str(params)
        panel = Panel(
            body,
            title=f"[bold {color}]{tool_name}[/]",
            border_style=self._theme.border,
            expand=False,
        )
        self._console.print(panel)

    def render_tool_result(self, tool_name: str, result: str, agent: str) -> None:
        """Show a panel with tool result, sanitized and truncated to 500 chars."""
        if not tool_name:
            tool_name = "(tool)"
        color = self._theme.agent_color(agent)
        sanitized = sanitize_tool_result(result)
        display = sanitized if len(sanitized) <= _TOOL_RESULT_MAX else sanitized[:_TOOL_RESULT_MAX] + "…"
        panel = Panel(
            display,
            title=f"[bold {color}]{tool_name} result[/]",
            border_style=self._theme.success,
            expand=False,
        )
        self._console.print(panel)

    def render_confirm_prompt(
        self,
        confirm_id: str,
        tool_name: str,
        params: dict,
        agent: str,
    ) -> None:
        """Show a yellow-bordered confirmation panel with y/n/a options."""
        try:
            body = json.dumps(params, indent=2, default=str)
        except (TypeError, ValueError):
            body = str(params)
        content = f"{tool_name}\n{body}\n\n[bold yellow](y)es / (n)o / (a)lways[/]"
        panel = Panel(
            content,
            title="[bold yellow]Confirm tool call[/]",
            border_style="yellow",
            expand=False,
        )
        self._console.print(panel)

    # -- System / errors --

    def render_error(self, error: str) -> None:
        """Display an error message in red with Error prefix."""
        self._console.print(Text(f"Error: {error}", style=self._theme.error))

    def render_system(self, text: str) -> None:
        """Display a dim italic system message."""
        self._console.print(Text(text, style=self._theme.system))

    # -- Help --

    def render_help(self, commands_by_tier: dict[str, list]) -> None:
        """Display help table organized by command tier."""
        table = Table(title="Commands", show_header=True, border_style=self._theme.border)
        table.add_column("Command", style="bold cyan")
        table.add_column("Description")
        table.add_column("Tier", style=self._theme.muted)
        for tier_name, commands in commands_by_tier.items():
            for cmd in commands:
                table.add_row(f"/{cmd.name}", cmd.description, tier_name)
        self._console.print(table)

    # -- Agents list --

    def render_agents_list(self, agents: list[dict], current_agent: str) -> None:
        """Display a table of available agents with the current one marked."""
        table = Table(title="Agents", show_header=True, border_style=self._theme.border)
        table.add_column("", width=2)
        table.add_column("Agent", style="bold")
        table.add_column("Description")
        for agent in agents:
            agent_id = agent.get("id", agent.get("name", ""))
            marker = "●" if agent_id == current_agent else ""
            color = self._theme.agent_color(agent_id)
            table.add_row(marker, Text(f"@{agent_id}", style=f"bold {color}"), agent.get("description", ""))
        self._console.print(table)

    # -- Sessions table --

    def render_sessions_table(
        self, sessions: list, title: str = "Sessions",
    ) -> None:
        """Display a Rich table of session summaries."""
        if not sessions:
            self._console.print(Text("No sessions found.", style=self._theme.muted))
            return
        table = Table(title=title, show_header=True, border_style=self._theme.border)
        table.add_column("ID", style="bold", width=10)
        table.add_column("Agent", style="bold")
        table.add_column("Started", style=self._theme.muted)
        table.add_column("Messages", justify="right")
        table.add_column("Summary")
        for s in sessions:
            sid = s.session_id[:8] if hasattr(s, "session_id") else str(s.get("session_id", ""))[:8]
            agent = s.agent_name if hasattr(s, "agent_name") else str(s.get("agent_name", ""))
            ts = ""
            if hasattr(s, "started_at") and s.started_at:
                ts = s.started_at.strftime("%Y-%m-%d %H:%M")
            msgs = str(s.message_count if hasattr(s, "message_count") else s.get("message_count", 0))
            summary = s.summary[:50] if hasattr(s, "summary") and s.summary else "(no summary)"
            color = self._theme.agent_color(agent)
            table.add_row(sid, Text(f"@{agent}", style=f"bold {color}"), ts, msgs, summary)
        self._console.print(table)

    # -- Memory results --

    def render_memory_results(self, results: list[dict], title: str = "Memory Results") -> None:
        """Display memory search results or 'No results' message."""
        if not results:
            self._console.print(Text("No results found.", style=self._theme.muted))
            return
        table = Table(title=title, show_header=True, border_style=self._theme.border)
        table.add_column("ID", style="bold")
        table.add_column("Content")
        table.add_column("Domain", style=self._theme.muted)
        table.add_column("Score", justify="right")
        for rec in results:
            table.add_row(
                str(rec.get("id", "")),
                str(rec.get("content", "")),
                str(rec.get("domain", "")),
                str(rec.get("score", "")),
            )
        self._console.print(table)

    # -- Tools list --

    def render_tools_list(self, tools: list[dict], agent: str) -> None:
        """Display available tools for an agent."""
        if not tools:
            self._console.print(Text("No tools available.", style=self._theme.muted))
            return
        table = Table(title=f"Tools for @{agent}", show_header=True, border_style=self._theme.border)
        table.add_column("Name", style="bold")
        table.add_column("Type", style=self._theme.muted)
        table.add_column("Description")
        for tool in tools:
            table.add_row(
                tool.get("name", ""),
                tool.get("type", ""),
                tool.get("description", ""),
            )
        self._console.print(table)

    # -- Agent detail --

    def render_agent_detail(self, agent: dict) -> None:
        """Display detailed information about a single agent.

        Shows name, description, model info, tools count, memory config,
        and enabled status in a bordered panel.
        """
        agent_id = agent.get("id", agent.get("name", "unknown"))
        color = self._theme.agent_color(agent_id)

        lines: list[str] = []
        lines.append(f"Name: {agent_id}")

        description = agent.get("description", "")
        if description:
            lines.append(f"Description: {description}")

        enabled = agent.get("enabled")
        if enabled is not None:
            lines.append(f"Enabled: {enabled}")

        # Model info
        models = agent.get("models")
        if models and isinstance(models, dict):
            preferred = models.get("preferred", "auto")
            lines.append(f"Model: {preferred}")
        elif models and isinstance(models, str):
            lines.append(f"Model: {models}")

        # Tools count
        tools = agent.get("tools")
        if tools is not None:
            if isinstance(tools, list):
                lines.append(f"Tools: {len(tools)} tools")
            elif isinstance(tools, dict):
                total = sum(len(v) if isinstance(v, list) else 1 for v in tools.values())
                lines.append(f"Tools: {total} tools")
        else:
            lines.append("Tools: 0 tools")

        # Memory config
        memory = agent.get("memory")
        if memory and isinstance(memory, dict):
            domain = memory.get("own_domain", "")
            if domain:
                lines.append(f"Memory domain: {domain}")

        panel = Panel(
            "\n".join(lines),
            title=f"[bold {color}]@{agent_id}[/]",
            border_style=self._theme.border,
            expand=False,
        )
        self._console.print(panel)

    # -- Agent config template --

    def render_agent_new_template(self, config_dir: str) -> None:
        """Display the YAML template for creating a new agent config."""
        template = (
            "name: <agent-name>\n"
            "description: >\n"
            "  Describe what this agent does\n"
            "enabled: true\n"
            "models:\n"
            "  preferred: null\n"
            "  fallback: null\n"
            "  auto: true\n"
            "  complexity: medium\n"
            "tools:\n"
            "  builtin:\n"
            "    - Bash\n"
            "    - Read\n"
            "  modules: {}\n"
            "memory:\n"
            "  own_domain: <agent-name>\n"
            "  readable_domains: null\n"
            "  can_read_shared: true\n"
            "  can_write: true\n"
        )
        syntax = Syntax(template, "yaml", theme="monokai")
        panel = Panel(
            syntax,
            title="[bold cyan]New Agent Template[/]",
            border_style=self._theme.border,
            expand=False,
        )
        self._console.print(panel)
        self._console.print(
            Text(
                f"Create a new directory under {config_dir}/<agent-name>/ "
                f"with agent.yaml, prompt.md, and soul.md",
                style=self._theme.system,
            )
        )
        self._console.print(
            Text("Run /reload after creating the config to load the new agent.", style=self._theme.system)
        )

    # -- Agent edit path --

    def render_agent_edit_path(self, agent_name: str, config_path: str) -> None:
        """Display the config path for editing an agent."""
        self._console.print(
            Text(f"Agent config: {config_path}", style=self._theme.system)
        )

    # -- Tool detail --

    def render_tool_detail(self, tool: dict, agent: str) -> None:
        """Display detailed info about a single tool."""
        color = self._theme.agent_color(agent)
        lines = []
        for key, value in tool.items():
            lines.append(f"{key}: {value}")
        panel = Panel(
            "\n".join(lines),
            title=f"[bold {color}]{tool.get('name', 'Tool')}[/]",
            border_style=self._theme.border,
            expand=False,
        )
        self._console.print(panel)

    # -- File view --

    def render_file_view(self, path: str, content: str, language: str) -> None:
        """Display file content with syntax highlighting."""
        syntax = Syntax(content, language, theme="monokai", line_numbers=True)
        panel = Panel(syntax, title=f"[bold]{path}[/]", border_style=self._theme.border, expand=False)
        self._console.print(panel)

    # -- Diff --

    def render_diff(self, diff: str, path: str = "") -> None:
        """Display a diff with syntax highlighting, or 'No changes' if empty."""
        if not diff:
            label = f"No changes found in {path}" if path else "No changes found"
            self._console.print(Text(label, style=self._theme.muted))
            return
        syntax = Syntax(diff, "diff", theme="monokai")
        title = f"[bold]Diff: {Path(path).name}[/]" if path else "[bold]git diff[/]"
        panel = Panel(syntax, title=title, border_style=self._theme.border, expand=False)
        self._console.print(panel)

    # -- Audit log --

    def render_audit_entries(self, entries: list[dict], title: str = "Audit Log") -> None:
        """Display audit log entries as a Rich table, or a 'no entries' message."""
        if not entries:
            self._console.print(Text("No audit entries found.", style=self._theme.muted))
            return
        table = Table(title=title, show_header=True, border_style=self._theme.border)
        table.add_column("Timestamp", style=self._theme.muted)
        table.add_column("Agent", style="bold")
        table.add_column("Tool")
        table.add_column("Outcome")
        table.add_column("Duration (ms)", justify="right")
        table.add_column("Reason", style=self._theme.muted)
        for entry in entries:
            outcome = str(entry.get("outcome", ""))
            outcome_style = {
                "allowed": self._theme.success,
                "denied": self._theme.error,
                "failed": self._theme.warning,
            }.get(outcome, "")
            duration = entry.get("duration_ms")
            duration_str = str(duration) if duration is not None else "-"
            table.add_row(
                str(entry.get("timestamp", "")),
                str(entry.get("agent_name", "")),
                str(entry.get("tool_name", "")),
                Text(outcome, style=outcome_style),
                duration_str,
                str(entry.get("reason") or ""),
            )
        self._console.print(table)

    # -- Policy --

    def render_policy(self, engine: PolicyEngine, current_tier: str) -> None:
        """Display a Rich panel with policy engine state.

        Shows the current permission tier, global deny patterns, and
        tier-specific configuration (mode, confirm_default, auth, TTL).

        Args:
            engine: The PolicyEngine instance to display.
            current_tier: The name of the currently active permission tier.
        """
        lines: list[str] = []

        # Current tier header
        tier_upper = current_tier.upper()
        lines.append(f"[bold]Current Tier:[/] [bold cyan]{tier_upper}[/] ({current_tier})")
        lines.append("")

        # Global deny patterns
        lines.append("[bold]Global Deny Patterns:[/]")
        if engine.global_deny:
            for pattern in engine.global_deny:
                lines.append(f"  - {pattern}")
        else:
            lines.append("  None")
        lines.append("")

        # Tier configuration
        tier_cfg = engine.tier_config(current_tier)
        lines.append(f"[bold]Tier Configuration ({current_tier}):[/]")
        if tier_cfg is not None:
            lines.append(f"  Mode:            {tier_cfg.mode}")
            lines.append(f"  Confirm Default: {tier_cfg.confirm_default}")
            lines.append(f"  Requires Auth:   {tier_cfg.requires_auth}")
            lines.append(f"  Token TTL:       {tier_cfg.token_ttl}s")
            lines.append(f"  Max TTL:         {tier_cfg.max_ttl}s")
        else:
            lines.append("  No tier config available — tier not configured")

        content = "\n".join(lines)
        panel = Panel(
            content,
            title="[bold]Security Policy[/]",
            border_style=self._theme.border,
            expand=False,
        )
        self._console.print(panel)

    # -- Setup dashboard --

    def render_setup_dashboard(self, providers: list[dict]) -> None:
        """Display the credential status dashboard as a Rich table.

        Args:
            providers: List of dicts with keys: name, configured (bool), detail (str).
                       Empty list renders a 'no providers' message.
        """
        if not providers:
            self._console.print(Text("No providers configured.", style=self._theme.muted))
            return

        table = Table(
            title="Credential Status",
            show_header=True,
            border_style=self._theme.border,
        )
        table.add_column("Provider", style="bold")
        table.add_column("Status")
        table.add_column("Details", style=self._theme.muted)

        for provider in providers:
            name = provider.get("name", "")
            configured = provider.get("configured", False)
            detail = provider.get("detail", "")

            if configured:
                marker = Text("\u25cf Configured", style=self._theme.success)
            else:
                marker = Text("\u25cb Not Configured", style=self._theme.error)

            table.add_row(name, marker, detail)

        self._console.print(table)

    # -- Navigation / status --

    def render_breadcrumb(self, breadcrumb: str) -> None:
        """Display a bold breadcrumb path."""
        self._console.print(Text(breadcrumb, style="bold"))

    def render_status_bar(
        self,
        agent: str,
        model: str,
        tokens: int,
        workers: int = 0,
    ) -> None:
        """Display a reverse-styled status line."""
        color = self._theme.agent_color(agent)
        parts = f" {agent} | {model} | {tokens} tokens"
        if workers:
            parts += f" | {workers} workers"
        parts += " "
        self._console.print(Text(parts, style=self._theme.status_bar))

    # -- Split mode --

    def render_split_layout(
        self,
        split_manager: "SplitManager",
        left_content: str,
        right_content: str,
    ) -> None:
        """Render two side-by-side panels for split mode."""
        from rich.columns import Columns

        left_color = self._theme.agent_color(split_manager.left_agent)
        right_color = self._theme.agent_color(split_manager.right_agent)

        left_panel = Panel(
            left_content,
            title=f"[bold {left_color}]@{split_manager.left_agent}[/]",
            border_style=left_color,
            expand=True,
        )
        right_panel = Panel(
            right_content,
            title=f"[bold {right_color}]@{split_manager.right_agent}[/]",
            border_style=right_color,
            expand=True,
        )
        self._console.print(Columns([left_panel, right_panel], equal=True, expand=True))

    def render_split_message(
        self,
        split_manager: "SplitManager",
        agent: str,
        text: str,
    ) -> None:
        """Render a message in the appropriate split pane."""
        pane = split_manager.pane_for(agent)
        color = self._theme.agent_color(agent)

        if pane == "left":
            left_content = f"@{agent}: {text}"
            right_content = ""
        else:
            left_content = ""
            right_content = f"@{agent}: {text}"

        self.render_split_layout(split_manager, left_content, right_content)

    # -- Break-glass --

    def render_breakglass_activated(self, ttl_minutes: int) -> None:
        """Display a prominent break-glass activation message.

        Args:
            ttl_minutes: The TTL in minutes for the break-glass session.
        """
        content = (
            f"[bold red]BREAK-GLASS MODE ACTIVATED[/]\n"
            f"Elevated permissions for {ttl_minutes} minutes.\n"
            f"Global deny list is still enforced.\n"
            f"Use /breakglass off to deactivate."
        )
        panel = Panel(
            content,
            title="[bold red]Break-Glass[/]",
            border_style="red",
            expand=False,
        )
        self._console.print(panel)

    def render_breakglass_deactivated(self) -> None:
        """Display a break-glass deactivation message."""
        self._console.print(
            Text("Break-glass mode deactivated. Permissions reset to default.", style="bold yellow")
        )

    def render_breakglass_status(self, remaining_seconds: float) -> None:
        """Display the remaining time for break-glass mode.

        Args:
            remaining_seconds: Seconds remaining before auto-deactivation.
        """
        remaining_minutes = int(remaining_seconds // 60)
        remaining_secs = int(remaining_seconds % 60)
        self._console.print(
            Text(
                f"BREAK-GLASS [{remaining_minutes}m {remaining_secs}s remaining]",
                style="bold red",
            )
        )
