"""Tests for Task 5.6: Split Mode — side-by-side agent panes.

Split mode divides the console into two columns, routing messages by agent.
Toggle with /split, deactivate with /split off.

NO MOCKS — uses real SplitManager and renderer with StringIO.
"""

import io

from rich.console import Console

from corvus.tui.core.split_manager import SplitManager
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.theme import TuiTheme


def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    renderer = ChatRenderer(console, TuiTheme())
    return renderer, buf


def _output(buf: io.StringIO) -> str:
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


# ---------------------------------------------------------------------------
# SplitManager state
# ---------------------------------------------------------------------------


class TestSplitManagerState:
    """SplitManager tracks split mode state and pane assignments."""

    def test_initially_inactive(self) -> None:
        sm = SplitManager()
        assert not sm.active

    def test_activate(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        assert sm.active
        assert sm.left_agent == "homelab"
        assert sm.right_agent == "finance"

    def test_deactivate(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        sm.deactivate()
        assert not sm.active

    def test_pane_for_agent_left(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        assert sm.pane_for("homelab") == "left"

    def test_pane_for_agent_right(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        assert sm.pane_for("finance") == "right"

    def test_pane_for_unknown_agent(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        # Unknown agents go to left by default
        assert sm.pane_for("work") == "left"

    def test_display_label(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        label = sm.display_label
        assert "@homelab" in label
        assert "@finance" in label

    def test_display_label_inactive(self) -> None:
        sm = SplitManager()
        assert sm.display_label == ""

    def test_swap_panes(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        sm.swap()
        assert sm.left_agent == "finance"
        assert sm.right_agent == "homelab"

    def test_reassign(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        sm.activate("work", "docs")
        assert sm.left_agent == "work"
        assert sm.right_agent == "docs"


# ---------------------------------------------------------------------------
# Split rendering
# ---------------------------------------------------------------------------


class TestSplitRendering:
    """Renderer's render_split_message routes content to correct pane."""

    def test_render_split_layout(self) -> None:
        renderer, buf = _make_renderer()
        sm = SplitManager()
        sm.activate("homelab", "finance")
        renderer.render_split_layout(sm, "Left content here", "Right content here")
        output = _output(buf)
        assert "Left content" in output
        assert "Right content" in output

    def test_render_split_layout_shows_agent_headers(self) -> None:
        renderer, buf = _make_renderer()
        sm = SplitManager()
        sm.activate("homelab", "finance")
        renderer.render_split_layout(sm, "hello", "world")
        output = _output(buf)
        assert "@homelab" in output
        assert "@finance" in output

    def test_render_split_message(self) -> None:
        renderer, buf = _make_renderer()
        sm = SplitManager()
        sm.activate("homelab", "finance")
        renderer.render_split_message(sm, "homelab", "Server is up")
        output = _output(buf)
        assert "Server is up" in output
        assert "@homelab" in output

    def test_render_split_activated(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_system("Split mode activated: @homelab + @finance")
        output = _output(buf)
        assert "Split mode" in output


# ---------------------------------------------------------------------------
# Status bar with split mode
# ---------------------------------------------------------------------------


class TestSplitStatusBar:
    """Status bar shows split indicator when active."""

    def test_split_label_in_display(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        label = sm.display_label
        assert "SPLIT" in label


# ---------------------------------------------------------------------------
# Split mode toggle
# ---------------------------------------------------------------------------


class TestSplitModeToggle:
    """SplitManager toggle behavior."""

    def test_toggle_on(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        assert sm.active

    def test_toggle_off(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        sm.deactivate()
        assert not sm.active

    def test_double_activate_overwrites(self) -> None:
        sm = SplitManager()
        sm.activate("homelab", "finance")
        sm.activate("work", "docs")
        assert sm.left_agent == "work"
        assert sm.right_agent == "docs"
