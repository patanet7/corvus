"""WorkerScreen — subagent panel showing spawned workers and their status.

Displays the agent tree rooted at the current agent, with status
indicators for each child/background worker.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.screens.base import Screen
from corvus.tui.theme import TuiTheme


class WorkerScreen(Screen):
    """Interactive worker/subagent status screen."""

    def __init__(
        self,
        console: Console,
        theme: TuiTheme,
        agent_stack: AgentStack,
    ) -> None:
        super().__init__(console, theme)
        self._agent_stack = agent_stack

    @property
    def title(self) -> str:
        return "Workers"

    def render(self) -> None:
        """Render the worker tree and status table."""
        if self._agent_stack.depth == 0:
            self._console.print(
                Panel(
                    Text("No active agents", style="dim italic"),
                    title=self.title,
                    border_style=self._theme.tool_border,
                )
            )
            return

        current = self._agent_stack.current
        tree = Tree(
            Text(f"@{current.agent_name}", style=f"bold {self._theme.tool_border}"),
        )

        children = current.children if current.children else []
        if not children:
            tree.add(Text("(no workers)", style="dim italic"))
        else:
            for child in children:
                status_label = (
                    child.status.value
                    if hasattr(child.status, "value")
                    else str(child.status)
                )
                style = "bold green" if status_label == "running" else "dim"
                tree.add(Text(f"@{child.agent_name} [{status_label}]", style=style))

        panel = Panel(
            tree,
            title=self.title,
            subtitle=f"{len(children)} workers",
            border_style=self._theme.tool_border,
        )
        self._console.print(panel)
