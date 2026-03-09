"""MemoryScreen — memory hub browser with search results display.

Renders memory search results or recent memories in a formatted panel.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from corvus.tui.screens.base import Screen
from corvus.tui.theme import TuiTheme


class MemoryScreen(Screen):
    """Interactive memory hub browser screen."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        super().__init__(console, theme)
        self._results: list[dict] = []
        self._query: str = ""

    @property
    def title(self) -> str:
        if self._query:
            return f"Memory — '{self._query}'"
        return "Memory"

    def set_results(self, results: list[dict], query: str = "") -> None:
        """Set memory results to display."""
        self._results = results
        self._query = query

    def render(self) -> None:
        """Render memory results as a table."""
        table = Table(
            title=self.title,
            show_header=True,
            header_style=f"bold {self._theme.tool_border}",
            expand=True,
        )
        table.add_column("ID", width=10)
        table.add_column("Agent", width=15)
        table.add_column("Content")
        table.add_column("Score", width=8, justify="right")

        for r in self._results:
            rid = str(r.get("id", ""))[:8]
            agent = r.get("agent", "")
            content = r.get("content", r.get("text", ""))
            if len(content) > 80:
                content = content[:77] + "..."
            score = r.get("score", "")
            score_str = f"{score:.2f}" if isinstance(score, float) else str(score)
            table.add_row(rid, f"@{agent}" if agent else "-", content, score_str)

        if not self._results:
            table.add_row(
                Text("-", style="dim"),
                Text("-", style="dim"),
                Text("No memories found", style="dim italic"),
                Text("-", style="dim"),
            )

        panel = Panel(
            table,
            subtitle=f"{len(self._results)} results",
            border_style=self._theme.tool_border,
        )
        self._console.print(panel)
