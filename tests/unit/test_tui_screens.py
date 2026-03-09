"""Behavioral tests for Corvus TUI screens.

NO MOCKS. Real Rich Console with StringIO capture, real dataclass instances.
"""

from io import StringIO

import pytest
from rich.console import Console

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.protocol.base import SessionSummary
from corvus.tui.screens.agents import AgentScreen
from corvus.tui.screens.base import Screen
from corvus.tui.screens.memory import MemoryScreen
from corvus.tui.screens.sessions import SessionScreen
from corvus.tui.core.credentials import _get_credential_status
from corvus.tui.screens.setup import SetupScreen
from corvus.tui.screens.tools import ToolScreen
from corvus.tui.screens.workers import WorkerScreen
from corvus.tui.theme import TuiTheme


def _make_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    return console, buf


def _output(buf: StringIO) -> str:
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Screen base
# ---------------------------------------------------------------------------


class TestScreenBase:
    def test_screen_is_abstract(self) -> None:
        """Cannot instantiate Screen directly."""
        console, _ = _make_console()
        with pytest.raises(TypeError):
            Screen(console, TuiTheme())  # type: ignore[abstract]

    def test_screen_subclass_has_title(self) -> None:
        """Concrete screens must provide a title."""
        console, _ = _make_console()
        screen = SetupScreen(console, TuiTheme())
        assert isinstance(screen.title, str)
        assert len(screen.title) > 0


# ---------------------------------------------------------------------------
# SetupScreen
# ---------------------------------------------------------------------------


class TestSetupScreen:
    def test_setup_renders_table(self) -> None:
        console, buf = _make_console()
        screen = SetupScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        assert "Setup" in output
        assert "Provider" in output

    def test_setup_shows_providers(self) -> None:
        console, buf = _make_console()
        screen = SetupScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        assert "Anthropic" in output
        assert "Ollama" in output

    def test_setup_shows_status(self) -> None:
        console, buf = _make_console()
        screen = SetupScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        # At least one provider should show "OK" or "Missing"
        assert "OK" in output or "Missing" in output

    def test_scan_providers_returns_list(self) -> None:
        providers = _get_credential_status()
        assert isinstance(providers, list)
        assert len(providers) >= 5
        for p in providers:
            assert "name" in p
            assert "configured" in p
            assert "detail" in p

    def test_setup_shows_summary(self) -> None:
        console, buf = _make_console()
        screen = SetupScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        assert "configured" in output.lower()


# ---------------------------------------------------------------------------
# AgentScreen
# ---------------------------------------------------------------------------


class TestAgentScreen:
    def test_agents_empty(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        screen = AgentScreen(console, TuiTheme(), stack)
        screen.render()
        output = _output(buf)
        assert "No agents" in output or "0 agents" in output

    def test_agents_with_data(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        screen = AgentScreen(console, TuiTheme(), stack)
        screen.set_agents([
            {"id": "huginn", "description": "Router agent"},
            {"id": "homelab", "description": "Home automation"},
        ])
        screen.render()
        output = _output(buf)
        assert "huginn" in output
        assert "homelab" in output
        assert "2 agents" in output

    def test_agents_current_marked(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        stack.push("huginn", session_id="")
        screen = AgentScreen(console, TuiTheme(), stack)
        screen.set_agents([
            {"id": "huginn", "description": "Router"},
            {"id": "homelab", "description": "Homelab"},
        ])
        screen.render()
        output = _output(buf)
        assert "active" in output.lower()

    def test_agents_title(self) -> None:
        console, _ = _make_console()
        screen = AgentScreen(console, TuiTheme(), AgentStack())
        assert screen.title == "Agents"


# ---------------------------------------------------------------------------
# SessionScreen
# ---------------------------------------------------------------------------


class TestSessionScreen:
    def test_sessions_empty(self) -> None:
        console, buf = _make_console()
        screen = SessionScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        assert "No sessions" in output or "0 sessions" in output

    def test_sessions_with_data(self) -> None:
        console, buf = _make_console()
        screen = SessionScreen(console, TuiTheme())
        screen.set_sessions([
            SessionSummary(session_id="abc12345", agent_name="homelab", summary="Fix router", message_count=5),
            SessionSummary(session_id="def67890", agent_name="finance", summary="Budget review", message_count=12),
        ])
        screen.render()
        output = _output(buf)
        assert "homelab" in output
        assert "finance" in output
        assert "Fix router" in output
        assert "2 sessions" in output

    def test_sessions_with_filter(self) -> None:
        console, buf = _make_console()
        screen = SessionScreen(console, TuiTheme())
        screen.set_filter("router")
        screen.set_sessions([
            SessionSummary(session_id="abc12345", agent_name="homelab", summary="Fix router", message_count=5),
        ])
        screen.render()
        output = _output(buf)
        assert "router" in output.lower()

    def test_sessions_title_with_filter(self) -> None:
        console, _ = _make_console()
        screen = SessionScreen(console, TuiTheme())
        screen.set_filter("test")
        assert "test" in screen.title


# ---------------------------------------------------------------------------
# MemoryScreen
# ---------------------------------------------------------------------------


class TestMemoryScreen:
    def test_memory_empty(self) -> None:
        console, buf = _make_console()
        screen = MemoryScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        assert "No memories" in output or "0 results" in output

    def test_memory_with_results(self) -> None:
        console, buf = _make_console()
        screen = MemoryScreen(console, TuiTheme())
        screen.set_results([
            {"id": "mem1", "agent": "homelab", "content": "Router IP is 192.168.1.1", "score": 0.95},
            {"id": "mem2", "agent": "homelab", "content": "DNS server at 1.1.1.1", "score": 0.82},
        ], query="network")
        screen.render()
        output = _output(buf)
        assert "192.168" in output
        assert "2 results" in output

    def test_memory_title_with_query(self) -> None:
        console, _ = _make_console()
        screen = MemoryScreen(console, TuiTheme())
        screen.set_results([], query="test query")
        assert "test query" in screen.title

    def test_memory_truncates_long_content(self) -> None:
        console, buf = _make_console()
        screen = MemoryScreen(console, TuiTheme())
        long_content = "A" * 200
        screen.set_results([
            {"id": "mem1", "agent": "test", "content": long_content, "score": 1.0},
        ])
        screen.render()
        output = _output(buf)
        # Content should be truncated — either by our "..." or Rich's "…"
        assert "..." in output or "\u2026" in output


# ---------------------------------------------------------------------------
# ToolScreen
# ---------------------------------------------------------------------------


class TestToolScreen:
    def test_tools_empty(self) -> None:
        console, buf = _make_console()
        screen = ToolScreen(console, TuiTheme())
        screen.render()
        output = _output(buf)
        assert "No tools" in output or "0 tools" in output

    def test_tools_with_data(self) -> None:
        console, buf = _make_console()
        screen = ToolScreen(console, TuiTheme())
        screen.set_tools([
            {"name": "read_file", "description": "Read a file from disk", "mutation": False},
            {"name": "write_file", "description": "Write content to a file", "mutation": True},
        ], agent="homelab")
        screen.render()
        output = _output(buf)
        assert "read_file" in output
        assert "write_file" in output
        assert "homelab" in output

    def test_tools_shows_mutation_flag(self) -> None:
        console, buf = _make_console()
        screen = ToolScreen(console, TuiTheme())
        screen.set_tools([
            {"name": "dangerous_tool", "description": "Does something risky", "mutation": True},
        ])
        screen.render()
        output = _output(buf)
        assert "yes" in output.lower()

    def test_tools_title_with_agent(self) -> None:
        console, _ = _make_console()
        screen = ToolScreen(console, TuiTheme())
        screen.set_tools([], agent="finance")
        assert "finance" in screen.title


# ---------------------------------------------------------------------------
# WorkerScreen
# ---------------------------------------------------------------------------


class TestWorkerScreen:
    def test_workers_no_agents(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        screen = WorkerScreen(console, TuiTheme(), stack)
        screen.render()
        output = _output(buf)
        assert "No active" in output

    def test_workers_no_children(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        stack.push("huginn", session_id="")
        screen = WorkerScreen(console, TuiTheme(), stack)
        screen.render()
        output = _output(buf)
        assert "huginn" in output
        assert "no workers" in output.lower() or "0 workers" in output

    def test_workers_with_children(self) -> None:
        console, buf = _make_console()
        stack = AgentStack()
        stack.push("huginn", session_id="")
        stack.spawn("homelab", session_id="")
        screen = WorkerScreen(console, TuiTheme(), stack)
        screen.render()
        output = _output(buf)
        assert "huginn" in output
        assert "homelab" in output

    def test_workers_title(self) -> None:
        console, _ = _make_console()
        screen = WorkerScreen(console, TuiTheme(), AgentStack())
        assert screen.title == "Workers"
