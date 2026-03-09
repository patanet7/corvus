"""SidebarPanel — toggleable right-side panel with collapsible sections.

The sidebar shows contextual information alongside the main chat:
agent tree, tool list, and session info. It can be toggled with Ctrl+B.
"""

from rich.console import Console, ConsoleRenderable, Group
from rich.panel import Panel
from rich.text import Text

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.panels.sections import (
    AgentTreeSection,
    CollapsibleSection,
    SessionListSection,
    ToolListSection,
    WorkerTreeSection,
)
from corvus.tui.theme import TuiTheme


class SidebarPanel:
    """Toggleable sidebar panel with collapsible sections.

    Sections:
    - Agents: shows the agent stack hierarchy
    - Tools: shows available tools for current agent

    The sidebar is rendered as a Rich Panel and can be embedded in
    a Layout for split-screen display.
    """

    def __init__(
        self,
        agent_stack: AgentStack,
        theme: TuiTheme,
    ) -> None:
        self._agent_stack = agent_stack
        self._theme = theme
        self._visible: bool = False

        self._agent_section = CollapsibleSection("Agents", theme)
        self._tool_section = CollapsibleSection("Tools", theme)
        self._worker_section = CollapsibleSection("Workers", theme)
        self._session_section = CollapsibleSection("Sessions", theme)
        self._agent_tree = AgentTreeSection(agent_stack, theme)
        self._tool_list = ToolListSection(theme)
        self._worker_tree = WorkerTreeSection(agent_stack, theme)
        self._session_list = SessionListSection(theme)

    @property
    def visible(self) -> bool:
        """Whether the sidebar is currently visible."""
        return self._visible

    def toggle(self) -> None:
        """Toggle sidebar visibility."""
        self._visible = not self._visible

    def show(self) -> None:
        """Show the sidebar."""
        self._visible = True

    def hide(self) -> None:
        """Hide the sidebar."""
        self._visible = False

    def toggle_section(self, section_name: str) -> None:
        """Toggle a specific section by name."""
        if section_name == "agents":
            self._agent_section.toggle()
        elif section_name == "tools":
            self._tool_section.toggle()
        elif section_name == "workers":
            self._worker_section.toggle()
        elif section_name == "sessions":
            self._session_section.toggle()

    def set_tools(self, tools: list[dict]) -> None:
        """Update the tool list for the tools section."""
        self._tool_list.set_tools(tools)

    def set_sessions(self, sessions: list[dict]) -> None:
        """Update the session list for the sessions section."""
        self._session_list.set_sessions(sessions)

    def render(self) -> ConsoleRenderable:
        """Render the sidebar as a panel with collapsible sections."""
        if not self._visible:
            return Text("")

        parts: list[ConsoleRenderable] = []

        agent_content = self._agent_tree.render()
        parts.append(self._agent_section.render(agent_content))

        tool_content = self._tool_list.render()
        parts.append(self._tool_section.render(tool_content))

        worker_content = self._worker_tree.render()
        parts.append(self._worker_section.render(worker_content))

        session_content = self._session_list.render()
        parts.append(self._session_section.render(session_content))

        return Panel(
            Group(*parts),
            title="Sidebar",
            border_style=self._theme.border,
            width=30,
        )

    def render_to_console(self, console: Console) -> None:
        """Render the sidebar directly to a console."""
        if self._visible:
            console.print(self.render())
