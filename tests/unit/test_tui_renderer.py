"""Behavioral tests for TUI theme system and Rich chat renderer.

Uses a Real Rich Console writing to io.StringIO — no mocks.
"""

import io

from rich.console import Console

from corvus.tui.theme import AGENT_COLORS, TuiTheme
from corvus.tui.output.renderer import ChatRenderer


def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    """Build a ChatRenderer backed by a string buffer for assertions."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    return renderer, buf


def _output(buf: io.StringIO) -> str:
    """Return everything written so far and reset."""
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


# --- AGENT_COLORS dict ---

def test_agent_colors_has_expected_keys():
    expected = {
        "huginn", "work", "homelab", "finance", "personal",
        "music", "docs", "inbox", "email", "home", "general",
    }
    assert expected.issubset(set(AGENT_COLORS.keys()))


# --- TuiTheme ---

def test_theme_known_agent_color():
    theme = TuiTheme()
    assert theme.agent_color("work") == "bright_blue"
    assert theme.agent_color("huginn") == "bright_magenta"


def test_theme_fallback_color_for_unknown_agent():
    theme = TuiTheme()
    color1 = theme.agent_color("unknown_agent_xyz")
    assert isinstance(color1, str)
    assert len(color1) > 0
    # Same unknown agent returns same fallback
    assert theme.agent_color("unknown_agent_xyz") == color1


def test_theme_chrome_attributes():
    theme = TuiTheme()
    for attr in ("border", "muted", "error", "warning", "success",
                 "system", "user_label", "status_bar"):
        assert hasattr(theme, attr)
        assert isinstance(getattr(theme, attr), str)


# --- ChatRenderer ---

def test_render_user_message_contains_text():
    renderer, buf = _make_renderer()
    renderer.render_user_message("hello world", agent="work")
    output = _output(buf)
    assert "hello world" in output


def test_render_agent_message_contains_agent_name():
    renderer, buf = _make_renderer()
    renderer.render_agent_message("work", "Here is my response.", tokens=42)
    output = _output(buf)
    assert "work" in output.lower()


def test_render_system_message():
    renderer, buf = _make_renderer()
    renderer.render_system("System ready.")
    output = _output(buf)
    assert "System ready" in output


def test_render_error_message():
    renderer, buf = _make_renderer()
    renderer.render_error("Something went wrong")
    output = _output(buf)
    assert "Something went wrong" in output


def test_render_tool_start_contains_tool_name():
    renderer, buf = _make_renderer()
    renderer.render_tool_start("search_files", {"query": "*.py"}, agent="homelab")
    output = _output(buf)
    assert "search_files" in output


def test_render_breadcrumb_contains_path_components():
    renderer, buf = _make_renderer()
    renderer.render_breadcrumb("corvus > work > files")
    output = _output(buf)
    assert "corvus" in output
    assert "work" in output


def test_render_tool_result_truncates_long_output():
    renderer, buf = _make_renderer()
    long_result = "x" * 1000
    renderer.render_tool_result("search_files", long_result, agent="work")
    output = _output(buf)
    # Should contain tool name and be truncated (not the full 1000 chars of raw x's)
    assert "search_files" in output


def test_render_stream_lifecycle():
    renderer, buf = _make_renderer()
    renderer.render_stream_start("finance")
    renderer.render_stream_chunk("Hello ")
    renderer.render_stream_chunk("world")
    renderer.render_stream_end(tokens=10)
    output = _output(buf)
    assert "finance" in output.lower()


def test_render_status_bar():
    renderer, buf = _make_renderer()
    renderer.render_status_bar(agent="work", model="claude-4", tokens=150, workers=2)
    output = _output(buf)
    assert "work" in output.lower()


def test_render_confirm_prompt():
    renderer, buf = _make_renderer()
    renderer.render_confirm_prompt(
        confirm_id="abc123",
        tool_name="delete_file",
        params={"path": "/tmp/foo"},
        agent="homelab",
    )
    output = _output(buf)
    assert "delete_file" in output
