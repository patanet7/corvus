"""SidebarPanel — toggleable right-side panel with collapsible sections.

The sidebar shows contextual information alongside the main chat:
agent tree, tool list, and session info. It can be toggled with Ctrl+B.
"""

from rich.console import Console, ConsoleRenderable, Group
from rich.panel import Panel
from rich.text import Text

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.panels.sections import AgentTreeSection, CollapsibleSection, ToolListSection
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
        self._agent_tree = AgentTreeSection(agent_stack, theme)
        self._tool_list = ToolListSection(theme)

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

    def set_tools(self, tools: list[dict]) -> None:
        """Update the tool list for the tools section."""
        self._tool_list.set_tools(tools)

    def render(self) -> ConsoleRenderable:
        """Render the sidebar as a panel with collapsible sections."""
        if not self._visible:
            return Text("")

        parts: list[ConsoleRenderable] = []

        agent_content = self._agent_tree.render()
        parts.append(self._agent_section.render(agent_content))

        tool_content = self._tool_list.render()
        parts.append(self._tool_section.render(tool_content))

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
