"""ToolScreen — tool browser with detail view and history.

Displays available tools for the current agent, with detail expansion
for individual tools showing parameters and descriptions.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from corvus.tui.screens.base import Screen
from corvus.tui.theme import TuiTheme


class ToolScreen(Screen):
    """Interactive tool browser screen."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        super().__init__(console, theme)
        self._tools: list[dict] = []
        self._agent: str = ""

    @property
    def title(self) -> str:
        if self._agent:
            return f"Tools — @{self._agent}"
        return "Tools"

    def set_tools(self, tools: list[dict], agent: str = "") -> None:
        """Set the tool list for display."""
        self._tools = tools
        self._agent = agent

    def render(self) -> None:
        """Render the tool list as a table."""
        table = Table(
            title=self.title,
            show_header=True,
            header_style=f"bold {self._theme.tool_border}",
            expand=True,
        )
        table.add_column("Tool", style="bold")
        table.add_column("Description")
        table.add_column("Mutation", width=10, justify="center")

        for tool in self._tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            if len(desc) > 60:
                desc = desc[:57] + "..."
            mutation = tool.get("mutation", False)
            mutation_text = Text("yes", style="bold yellow") if mutation else Text("no", style="dim")
            table.add_row(name, desc, mutation_text)

        if not self._tools:
            table.add_row(
                Text("No tools available", style="dim italic"),
                "",
                Text("-", style="dim"),
            )

        panel = Panel(
            table,
            subtitle=f"{len(self._tools)} tools" + (f" for @{self._agent}" if self._agent else ""),
            border_style=self._theme.tool_border,
        )
        self._console.print(panel)
