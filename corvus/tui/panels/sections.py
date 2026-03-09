"""Collapsible sections and tree components for the Corvus TUI sidebar.

Provides building blocks for the sidebar panel: collapsible sections,
agent tree, worker tree, and tool list sections.
"""

from rich.console import ConsoleRenderable
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.theme import TuiTheme


class CollapsibleSection:
    """A section with a title that can be expanded or collapsed.

    When collapsed, only the title bar is visible. When expanded,
    the content is rendered below the title.
    """

    def __init__(self, title: str, theme: TuiTheme) -> None:
        self.title = title
        self._theme = theme
        self.expanded: bool = True

    def toggle(self) -> None:
        """Toggle the expanded/collapsed state."""
        self.expanded = not self.expanded

    def render(self, content: ConsoleRenderable) -> ConsoleRenderable:
        """Render the section as a panel (expanded) or a single line (collapsed)."""
        indicator = "▼" if self.expanded else "▶"
        header = f"{indicator} {self.title}"

        if self.expanded:
            return Panel(
                content,
                title=header,
                title_align="left",
                border_style=self._theme.border,
                expand=True,
            )
        return Text(header, style=self._theme.muted)


class AgentTreeSection:
    """Renders the agent stack as a tree in the sidebar.

    Shows the full agent hierarchy with current agent highlighted
    and child agents listed beneath their parent.
    """

    def __init__(self, agent_stack: AgentStack, theme: TuiTheme) -> None:
        self._agent_stack = agent_stack
        self._theme = theme

    def render(self) -> ConsoleRenderable:
        """Build a Rich Tree of the agent hierarchy."""
        if self._agent_stack.depth == 0:
            return Text("(no agents)", style=self._theme.muted)

        # Use breadcrumb to show the stack path, then show children
        breadcrumb = self._agent_stack.breadcrumb
        parts = breadcrumb.split(" > ")
        root_name = parts[0]
        tree = Tree(
            Text(f"@{root_name}", style=f"bold {self._theme.tool_border}"),
        )

        # Add intermediate stack entries
        current_branch = tree
        for name in parts[1:]:
            current_branch = current_branch.add(Text(f"@{name}", style="bold"))

        # Add child workers of the current agent
        current = self._agent_stack.current
        if current.children:
            for child in current.children:
                status_label = (
                    child.status.value
                    if hasattr(child.status, "value")
                    else str(child.status)
                )
                current_branch.add(Text(
                    f"@{child.agent_name} [{status_label}]",
                    style="dim",
                ))

        return tree


class WorkerTreeSection:
    """Renders child workers of the current agent as a tree."""

    def __init__(self, agent_stack: AgentStack, theme: TuiTheme) -> None:
        self._agent_stack = agent_stack
        self._theme = theme

    def render(self) -> ConsoleRenderable:
        """Build a Rich Tree of child workers."""
        if self._agent_stack.depth == 0:
            return Text("(no workers)", style=self._theme.muted)
        current = self._agent_stack.current
        if not current.children:
            return Text("(no workers)", style=self._theme.muted)
        tree = Tree(Text("Workers", style=f"bold {self._theme.tool_border}"))
        for child in current.children:
            status_label = child.status.value if hasattr(child.status, "value") else str(child.status)
            tree.add(Text(f"@{child.agent_name} [{status_label}]", style="dim"))
        return tree


class SessionListSection:
    """Renders a compact list of recent sessions for the sidebar."""

    def __init__(self, theme: TuiTheme) -> None:
        self._theme = theme
        self._sessions: list[dict] = []

    def set_sessions(self, sessions: list[dict]) -> None:
        """Update the session list."""
        self._sessions = sessions

    def render(self) -> ConsoleRenderable:
        """Render sessions as a compact list (max 5)."""
        if not self._sessions:
            return Text("(no sessions)", style=self._theme.muted)
        lines: list[Text] = []
        for s in self._sessions[:5]:
            sid = str(s.get("session_id", ""))[:8]
            agent = s.get("agent_name", "unknown")
            lines.append(Text(f" {sid} @{agent}", style=self._theme.tool_name))
        result = Text()
        for i, line in enumerate(lines):
            result.append(line)
            if i < len(lines) - 1:
                result.append("\n")
        return result


class ToolListSection:
    """Renders a compact list of available tools for the sidebar."""

    def __init__(self, theme: TuiTheme) -> None:
        self._theme = theme
        self._tools: list[dict] = []

    def set_tools(self, tools: list[dict]) -> None:
        """Update the tool list."""
        self._tools = tools

    def render(self) -> ConsoleRenderable:
        """Render tools as a compact list."""
        if not self._tools:
            return Text("(no tools)", style=self._theme.muted)

        lines: list[Text] = []
        for tool in self._tools:
            name = tool.get("name", "unknown")
            mutation = tool.get("mutation", False)
            prefix = "!" if mutation else " "
            lines.append(Text(f" {prefix}{name}", style=self._theme.tool_name))

        result = Text()
        for i, line in enumerate(lines):
            result.append(line)
            if i < len(lines) - 1:
                result.append("\n")
        return result
