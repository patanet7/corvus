"""Rich-based chat renderer for the Corvus TUI."""

import json

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from corvus.tui.theme import TuiTheme

_TOOL_RESULT_MAX = 500


class ChatRenderer:
    """Renders chat messages, tool calls, and UI chrome to a Rich Console."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        self._console = console
        self._theme = theme

    # -- User / agent messages --

    def render_user_message(self, text: str, agent: str) -> None:
        """Display a user message with 'You:' label."""
        label = Text("You: ", style=self._theme.user_label)
        label.append(text)
        self._console.print(label)

    def render_agent_message(self, agent: str, text: str, tokens: int = 0) -> None:
        """Display an agent response with the agent name in its color."""
        color = self._theme.agent_color(agent)
        header = Text(f"{agent}: ", style=f"bold {color}")
        self._console.print(header)
        self._console.print(Markdown(text))
        if tokens:
            self._console.print(
                Text(f"  [{tokens} tokens]", style=self._theme.muted)
            )

    # -- Streaming --

    def render_stream_start(self, agent: str) -> None:
        """Print the agent label at the start of a streamed response."""
        color = self._theme.agent_color(agent)
        self._console.print(Text(f"{agent}: ", style=f"bold {color}"), end="")

    def render_stream_chunk(self, chunk: str) -> None:
        """Print a raw streaming chunk without trailing newline."""
        self._console.print(chunk, end="", highlight=False)

    def render_stream_end(self, tokens: int = 0) -> None:
        """Finish a streamed response."""
        self._console.print()  # newline
        if tokens:
            self._console.print(
                Text(f"  [{tokens} tokens]", style=self._theme.muted)
            )

    # -- Tool calls --

    def render_tool_start(self, tool_name: str, params: dict, agent: str) -> None:
        """Show a panel indicating a tool call is starting."""
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
        """Show a panel with tool result, truncated to 500 chars."""
        color = self._theme.agent_color(agent)
        display = result if len(result) <= _TOOL_RESULT_MAX else result[:_TOOL_RESULT_MAX] + "..."
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
        """Display an error message in red."""
        self._console.print(Text(error, style=self._theme.error))

    def render_system(self, text: str) -> None:
        """Display a dim italic system message."""
        self._console.print(Text(text, style=self._theme.system))

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
