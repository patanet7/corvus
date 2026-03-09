"""AgentScreen — agent browser, creation template, and edit guidance.

Displays all available agents with their descriptions, current status,
and provides templates for creating new agents.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.screens.base import Screen
from corvus.tui.theme import TuiTheme


class AgentScreen(Screen):
    """Interactive agent browser and management screen."""

    def __init__(
        self,
        console: Console,
        theme: TuiTheme,
        agent_stack: AgentStack,
    ) -> None:
        super().__init__(console, theme)
        self._agent_stack = agent_stack
        self._agents: list[dict] = []

    @property
    def title(self) -> str:
        return "Agents"

    def set_agents(self, agents: list[dict]) -> None:
        """Set the agent list (fetched from gateway)."""
        self._agents = agents

    def render(self) -> None:
        """Render the agent list as a table with status indicators."""
        table = Table(
            title=self.title,
            show_header=True,
            header_style=f"bold {self._theme.tool_border}",
            expand=True,
        )
        table.add_column("Agent", style="bold")
        table.add_column("Description")
        table.add_column("Status", width=12, justify="center")

        current_name = (
            self._agent_stack.current.agent_name
            if self._agent_stack.depth > 0
            else ""
        )

        for agent in self._agents:
            agent_id = agent.get("id", "")
            desc = agent.get("description", "")
            if agent_id == current_name:
                status = Text("active", style="bold green")
                name_text = Text(f"@{agent_id}", style=f"bold {self._theme.tool_border}")
            else:
                status = Text("idle", style="dim")
                name_text = Text(f"@{agent_id}")
            table.add_row(name_text, desc, status)

        if not self._agents:
            table.add_row(
                Text("No agents loaded", style="dim italic"),
                "",
                Text("-", style="dim"),
            )

        panel = Panel(
            table,
            subtitle=f"{len(self._agents)} agents available",
            border_style=self._theme.tool_border,
        )
        self._console.print(panel)
