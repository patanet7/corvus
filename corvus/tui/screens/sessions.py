"""SessionScreen — session history browser with search and resume.

Displays a table of past sessions with agent, timestamp, summary, and
message count.  Supports filtering by search query.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from corvus.tui.protocol.base import SessionSummary
from corvus.tui.screens.base import Screen
from corvus.tui.theme import TuiTheme


class SessionScreen(Screen):
    """Interactive session history browser screen."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        super().__init__(console, theme)
        self._sessions: list[SessionSummary] = []
        self._filter_query: str = ""

    @property
    def title(self) -> str:
        if self._filter_query:
            return f"Sessions — '{self._filter_query}'"
        return "Sessions"

    def set_sessions(self, sessions: list[SessionSummary]) -> None:
        """Set the session list (fetched from gateway)."""
        self._sessions = sessions

    def set_filter(self, query: str) -> None:
        """Set a filter query for display."""
        self._filter_query = query

    def render(self) -> None:
        """Render the session list as a table."""
        table = Table(
            title=self.title,
            show_header=True,
            header_style=f"bold {self._theme.tool_border}",
            expand=True,
        )
        table.add_column("ID", width=10)
        table.add_column("Agent", width=15)
        table.add_column("Summary")
        table.add_column("Messages", width=10, justify="right")

        for s in self._sessions:
            sid = (s.session_id or "")[:8]
            agent = s.agent_name or "unknown"
            summary = s.summary or ""
            msgs = str(s.message_count) if s.message_count else "0"
            table.add_row(sid, f"@{agent}", summary, msgs)

        if not self._sessions:
            table.add_row(
                Text("-", style="dim"),
                Text("-", style="dim"),
                Text("No sessions found", style="dim italic"),
                Text("-", style="dim"),
            )

        subtitle = f"{len(self._sessions)} sessions"
        if self._filter_query:
            subtitle += f" matching '{self._filter_query}'"

        panel = Panel(
            table,
            subtitle=subtitle,
            border_style=self._theme.tool_border,
        )
        self._console.print(panel)
