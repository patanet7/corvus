"""Behavioral tests for corvus.tui.layout.terminal_layout.

All tests exercise the real TerminalLayout and Rich Console — no mocks.
Output capture uses Rich's StringIO-backed Console for verification.
"""

import io

import pytest
from rich.console import Console

from corvus.tui.layout.terminal_layout import LayoutMode, TerminalLayout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_console() -> Console:
    """Return a Console that writes to an in-memory buffer."""
    return Console(file=io.StringIO(), force_terminal=True, width=120, height=40)


def _get_output(console: Console) -> str:
    """Extract the captured output from a StringIO-backed Console."""
    file = console.file
    assert isinstance(file, io.StringIO)
    return file.getvalue()


# ---------------------------------------------------------------------------
# LayoutMode enum
# ---------------------------------------------------------------------------

class TestLayoutMode:
    """Verify the LayoutMode enum values."""

    def test_single_value(self) -> None:
        assert LayoutMode.SINGLE.value == "single"

    def test_split_value(self) -> None:
        assert LayoutMode.SPLIT.value == "split"

    def test_sidebar_value(self) -> None:
        assert LayoutMode.SIDEBAR.value == "sidebar"

    def test_members_count(self) -> None:
        assert len(LayoutMode) == 3


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------

class TestTerminalLayoutDefaults:
    """Verify default state of a freshly constructed TerminalLayout."""

    def test_default_mode_is_single(self) -> None:
        layout = TerminalLayout()
        assert layout.active_mode is LayoutMode.SINGLE

    def test_default_has_sidebar_false(self) -> None:
        layout = TerminalLayout()
        assert layout.has_sidebar is False

    def test_default_content_empty(self) -> None:
        layout = TerminalLayout()
        assert layout.header_content == ""
        assert layout.main_content == ""
        assert layout.sidebar_content == ""
        assert layout.status_content == ""
        assert layout.left_content == ""
        assert layout.right_content == ""


# ---------------------------------------------------------------------------
# Mode switching
# ---------------------------------------------------------------------------

class TestModeSwitch:
    """Verify set_mode transitions and property updates."""

    def test_switch_to_split(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SPLIT)
        assert layout.active_mode is LayoutMode.SPLIT

    def test_switch_to_sidebar(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        assert layout.active_mode is LayoutMode.SIDEBAR
        assert layout.has_sidebar is True

    def test_switch_back_to_single(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        layout.set_mode(LayoutMode.SINGLE)
        assert layout.active_mode is LayoutMode.SINGLE
        assert layout.has_sidebar is False

    def test_switch_to_same_mode(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SINGLE)
        assert layout.active_mode is LayoutMode.SINGLE

    def test_set_mode_rejects_string(self) -> None:
        layout = TerminalLayout()
        with pytest.raises(TypeError, match="Expected LayoutMode"):
            layout.set_mode("split")  # type: ignore[arg-type]

    def test_set_mode_rejects_none(self) -> None:
        layout = TerminalLayout()
        with pytest.raises(TypeError, match="Expected LayoutMode"):
            layout.set_mode(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# has_sidebar per mode
# ---------------------------------------------------------------------------

class TestHasSidebar:
    """Verify has_sidebar reflects the current mode correctly."""

    def test_single_no_sidebar(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SINGLE)
        assert layout.has_sidebar is False

    def test_split_no_sidebar(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SPLIT)
        assert layout.has_sidebar is False

    def test_sidebar_has_sidebar(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        assert layout.has_sidebar is True


# ---------------------------------------------------------------------------
# Rendering — SINGLE mode
# ---------------------------------------------------------------------------

class TestRenderSingle:
    """Verify render output in SINGLE mode."""

    def test_render_produces_output(self) -> None:
        layout = TerminalLayout()
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "corvus" in output

    def test_render_contains_header_content(self) -> None:
        layout = TerminalLayout()
        layout.header_content = "work > codex > researcher"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "work > codex > researcher" in output

    def test_render_contains_main_content(self) -> None:
        layout = TerminalLayout()
        layout.main_content = "Hello from the main pane"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "Hello from the main pane" in output

    def test_render_contains_status_content(self) -> None:
        layout = TerminalLayout()
        layout.status_content = "@work | claude-sonnet | 1.2k tokens"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "@work" in output

    def test_render_shows_corvus_title(self) -> None:
        layout = TerminalLayout()
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "corvus" in output


# ---------------------------------------------------------------------------
# Rendering — SPLIT mode
# ---------------------------------------------------------------------------

class TestRenderSplit:
    """Verify render output in SPLIT mode."""

    def test_render_split_produces_output(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SPLIT)
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert len(output) > 0

    def test_render_split_contains_left_content(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SPLIT)
        layout.left_content = "Left pane data"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "Left pane data" in output

    def test_render_split_contains_right_content(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SPLIT)
        layout.right_content = "Right pane data"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "Right pane data" in output

    def test_render_split_shows_pane_titles(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SPLIT)
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "left" in output
        assert "right" in output


# ---------------------------------------------------------------------------
# Rendering — SIDEBAR mode
# ---------------------------------------------------------------------------

class TestRenderSidebar:
    """Verify render output in SIDEBAR mode."""

    def test_render_sidebar_produces_output(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert len(output) > 0

    def test_render_sidebar_contains_main_content(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        layout.main_content = "Main area chat"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "Main area chat" in output

    def test_render_sidebar_contains_sidebar_content(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        layout.sidebar_content = "Agent tree here"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "Agent tree here" in output

    def test_render_sidebar_shows_sidebar_title(self) -> None:
        layout = TerminalLayout()
        layout.set_mode(LayoutMode.SIDEBAR)
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "sidebar" in output


# ---------------------------------------------------------------------------
# Render across mode switches
# ---------------------------------------------------------------------------

class TestRenderModeTransitions:
    """Verify rendering still works after switching modes."""

    def test_single_to_split_to_sidebar(self) -> None:
        layout = TerminalLayout()
        layout.main_content = "single-content"

        # Render in SINGLE
        console = _capture_console()
        layout.render(console)
        assert "single-content" in _get_output(console)

        # Switch to SPLIT and render
        layout.set_mode(LayoutMode.SPLIT)
        layout.left_content = "split-left"
        layout.right_content = "split-right"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "split-left" in output
        assert "split-right" in output

        # Switch to SIDEBAR and render
        layout.set_mode(LayoutMode.SIDEBAR)
        layout.sidebar_content = "sidebar-tools"
        console = _capture_console()
        layout.render(console)
        output = _get_output(console)
        assert "sidebar-tools" in output

    def test_render_multiple_times_same_mode(self) -> None:
        layout = TerminalLayout()
        layout.main_content = "first"
        console = _capture_console()
        layout.render(console)
        assert "first" in _get_output(console)

        layout.main_content = "second"
        console = _capture_console()
        layout.render(console)
        assert "second" in _get_output(console)


# ---------------------------------------------------------------------------
# Import from package __init__
# ---------------------------------------------------------------------------

class TestPackageImport:
    """Verify the layout package re-exports work."""

    def test_import_from_package(self) -> None:
        from corvus.tui.layout import LayoutMode as LM
        from corvus.tui.layout import TerminalLayout as TL

        assert LM is LayoutMode
        assert TL is TerminalLayout
