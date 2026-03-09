"""Behavioral tests for Corvus TUI panels and sections.

NO MOCKS. Real Rich Console with StringIO capture, real dataclass instances.
"""

from io import StringIO

from rich.console import Console
from rich.text import Text

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.panels.sections import AgentTreeSection, CollapsibleSection, ToolListSection
from corvus.tui.panels.sidebar import SidebarPanel
from corvus.tui.theme import TuiTheme


def _make_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    return console, buf


def _render_to_str(renderable: object) -> str:
    console, buf = _make_console()
    console.print(renderable)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# CollapsibleSection
# ---------------------------------------------------------------------------


class TestCollapsibleSection:
    def test_starts_expanded(self) -> None:
        section = CollapsibleSection("Test", TuiTheme())
        assert section.expanded is True

    def test_toggle(self) -> None:
        section = CollapsibleSection("Test", TuiTheme())
        section.toggle()
        assert section.expanded is False
        section.toggle()
        assert section.expanded is True

    def test_render_expanded_shows_panel(self) -> None:
        section = CollapsibleSection("Agents", TuiTheme())
        content = Text("hello")
        rendered = section.render(content)
        output = _render_to_str(rendered)
        assert "Agents" in output
        assert "hello" in output

    def test_render_collapsed_shows_title_only(self) -> None:
        section = CollapsibleSection("Agents", TuiTheme())
        section.toggle()  # collapse
        content = Text("hello")
        rendered = section.render(content)
        output = _render_to_str(rendered)
        assert "Agents" in output
        # Content should NOT appear when collapsed
        assert "hello" not in output

    def test_expanded_indicator(self) -> None:
        section = CollapsibleSection("Test", TuiTheme())
        content = Text("x")
        rendered = section.render(content)
        output = _render_to_str(rendered)
        assert "\u25bc" in output  # ▼

    def test_collapsed_indicator(self) -> None:
        section = CollapsibleSection("Test", TuiTheme())
        section.toggle()
        content = Text("x")
        rendered = section.render(content)
        output = _render_to_str(rendered)
        assert "\u25b6" in output  # ▶


# ---------------------------------------------------------------------------
# AgentTreeSection
# ---------------------------------------------------------------------------


class TestAgentTreeSection:
    def test_empty_stack(self) -> None:
        stack = AgentStack()
        tree = AgentTreeSection(stack, TuiTheme())
        output = _render_to_str(tree.render())
        assert "no agents" in output.lower()

    def test_single_agent(self) -> None:
        stack = AgentStack()
        stack.push("huginn", session_id="")
        tree = AgentTreeSection(stack, TuiTheme())
        output = _render_to_str(tree.render())
        assert "huginn" in output

    def test_nested_agents(self) -> None:
        stack = AgentStack()
        stack.push("huginn", session_id="")
        stack.push("homelab", session_id="")
        tree = AgentTreeSection(stack, TuiTheme())
        output = _render_to_str(tree.render())
        assert "huginn" in output
        assert "homelab" in output


# ---------------------------------------------------------------------------
# ToolListSection
# ---------------------------------------------------------------------------


class TestToolListSection:
    def test_empty(self) -> None:
        section = ToolListSection(TuiTheme())
        output = _render_to_str(section.render())
        assert "no tools" in output.lower()

    def test_with_tools(self) -> None:
        section = ToolListSection(TuiTheme())
        section.set_tools([
            {"name": "read_file", "mutation": False},
            {"name": "write_file", "mutation": True},
        ])
        output = _render_to_str(section.render())
        assert "read_file" in output
        assert "write_file" in output

    def test_mutation_prefix(self) -> None:
        section = ToolListSection(TuiTheme())
        section.set_tools([
            {"name": "dangerous", "mutation": True},
        ])
        output = _render_to_str(section.render())
        assert "!" in output


# ---------------------------------------------------------------------------
# SidebarPanel
# ---------------------------------------------------------------------------


class TestSidebarPanel:
    def test_starts_hidden(self) -> None:
        sidebar = SidebarPanel(AgentStack(), TuiTheme())
        assert sidebar.visible is False

    def test_toggle(self) -> None:
        sidebar = SidebarPanel(AgentStack(), TuiTheme())
        sidebar.toggle()
        assert sidebar.visible is True
        sidebar.toggle()
        assert sidebar.visible is False

    def test_show_hide(self) -> None:
        sidebar = SidebarPanel(AgentStack(), TuiTheme())
        sidebar.show()
        assert sidebar.visible is True
        sidebar.hide()
        assert sidebar.visible is False

    def test_render_hidden_produces_empty(self) -> None:
        sidebar = SidebarPanel(AgentStack(), TuiTheme())
        output = _render_to_str(sidebar.render())
        assert output.strip() == ""

    def test_render_visible_shows_sidebar(self) -> None:
        stack = AgentStack()
        stack.push("huginn", session_id="")
        sidebar = SidebarPanel(stack, TuiTheme())
        sidebar.show()
        output = _render_to_str(sidebar.render())
        assert "Sidebar" in output
        assert "Agents" in output

    def test_toggle_section(self) -> None:
        sidebar = SidebarPanel(AgentStack(), TuiTheme())
        sidebar.show()
        assert sidebar._agent_section.expanded is True
        sidebar.toggle_section("agents")
        assert sidebar._agent_section.expanded is False

    def test_set_tools(self) -> None:
        sidebar = SidebarPanel(AgentStack(), TuiTheme())
        sidebar.show()
        sidebar.set_tools([{"name": "test_tool", "mutation": False}])
        output = _render_to_str(sidebar.render())
        assert "test_tool" in output

    def test_render_to_console(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        stack.push("huginn", session_id="")
        sidebar = SidebarPanel(stack, TuiTheme())
        sidebar.show()
        sidebar.render_to_console(console)
        buf.seek(0)
        output = buf.read()
        assert "Sidebar" in output
