"""Behavioral tests for session export to markdown.

Uses REAL file I/O with temp directories — no mocks, no monkeypatch.
"""

import json
import tempfile
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.exporter import export_session_to_markdown
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Sample message fixtures (plain dicts matching SessionDetail.messages shape)
# ---------------------------------------------------------------------------

_BASIC_MESSAGES: list[dict] = [
    {"role": "user", "content": "Hello, how are you?"},
    {"role": "assistant", "agent": "huginn", "content": "I'm doing well, thanks!"},
]

_MULTI_AGENT_MESSAGES: list[dict] = [
    {"role": "user", "content": "Check my calendar"},
    {"role": "assistant", "agent": "huginn", "content": "Routing to @work..."},
    {"role": "assistant", "agent": "work", "content": "You have 3 meetings today."},
]

_TOOL_CALL_MESSAGES: list[dict] = [
    {"role": "user", "content": "What's the weather?"},
    {
        "role": "assistant",
        "agent": "homelab",
        "content": "Let me check that for you.",
        "tool_calls": [
            {
                "name": "get_weather",
                "parameters": {"location": "New York", "units": "metric"},
            }
        ],
    },
    {
        "role": "tool",
        "tool_name": "get_weather",
        "content": "72F, sunny",
    },
    {
        "role": "assistant",
        "agent": "homelab",
        "content": "It's 72F and sunny in New York.",
    },
]

_TIMESTAMPED_MESSAGES: list[dict] = [
    {"role": "user", "content": "ping", "timestamp": "2026-03-09T10:00:00Z"},
    {
        "role": "assistant",
        "agent": "huginn",
        "content": "pong",
        "timestamp": "2026-03-09T10:00:01Z",
    },
]


# ---------------------------------------------------------------------------
# Tests for export_session_to_markdown()
# ---------------------------------------------------------------------------


class TestExportSessionToMarkdown:
    """Verify that export_session_to_markdown writes correct markdown files."""

    def test_creates_file_on_disk(self) -> None:
        """Calling export should create a real file at the given path."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            result = export_session_to_markdown(_BASIC_MESSAGES, dest)
            assert result == dest
            assert dest.exists()
            assert dest.stat().st_size > 0

    def test_starts_with_header(self) -> None:
        """Exported file must start with '# Corvus Session Export'."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_BASIC_MESSAGES, dest)
            content = dest.read_text()
            assert content.startswith("# Corvus Session Export")

    def test_includes_agent_names_as_headers(self) -> None:
        """Agent names should appear as ## headers."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_MULTI_AGENT_MESSAGES, dest)
            content = dest.read_text()
            assert "## @huginn" in content
            assert "## @work" in content

    def test_includes_user_messages(self) -> None:
        """User messages should appear under a ## You header."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_BASIC_MESSAGES, dest)
            content = dest.read_text()
            assert "## You" in content
            assert "Hello, how are you?" in content

    def test_includes_message_content(self) -> None:
        """All message content should be present in the export."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_BASIC_MESSAGES, dest)
            content = dest.read_text()
            assert "Hello, how are you?" in content
            assert "I'm doing well, thanks!" in content

    def test_includes_tool_calls_with_parameters(self) -> None:
        """Tool calls should show the tool name and JSON parameters."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_TOOL_CALL_MESSAGES, dest)
            content = dest.read_text()
            assert "### Tool: get_weather" in content
            assert '"location"' in content
            assert '"New York"' in content

    def test_includes_tool_results(self) -> None:
        """Tool results should appear in the exported markdown."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_TOOL_CALL_MESSAGES, dest)
            content = dest.read_text()
            assert "72F, sunny" in content

    def test_includes_timestamps_when_present(self) -> None:
        """If messages have timestamps, they should appear in the output."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(_TIMESTAMPED_MESSAGES, dest)
            content = dest.read_text()
            assert "2026-03-09T10:00:00Z" in content
            assert "2026-03-09T10:00:01Z" in content

    def test_empty_messages_returns_path_with_minimal_content(self) -> None:
        """Exporting an empty message list still creates a valid file."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            result = export_session_to_markdown([], dest)
            assert result == dest
            content = dest.read_text()
            assert "# Corvus Session Export" in content


class TestExportDefaultPath:
    """Verify the default path generation when no explicit path is given."""

    def test_default_path_uses_date(self) -> None:
        """Default export path should contain today's date."""
        from corvus.tui.core.exporter import default_export_path

        path = default_export_path()
        today = date.today().isoformat()
        assert today in path.name
        assert path.name.startswith("corvus-export-")
        assert path.name.endswith(".md")

    def test_default_path_is_in_home(self) -> None:
        """Default export path should be under the user's home directory."""
        from corvus.tui.core.exporter import default_export_path

        path = default_export_path()
        assert str(path).startswith(str(Path.home()))


class TestExportToolCallEdgeCases:
    """Verify edge cases in tool call formatting."""

    def test_tool_call_with_empty_parameters(self) -> None:
        """Tool calls with empty params should still render cleanly."""
        messages: list[dict] = [
            {
                "role": "assistant",
                "agent": "work",
                "content": "Running...",
                "tool_calls": [{"name": "list_tasks", "parameters": {}}],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(messages, dest)
            content = dest.read_text()
            assert "### Tool: list_tasks" in content

    def test_multiple_tool_calls_in_one_message(self) -> None:
        """A message with multiple tool_calls should render each one."""
        messages: list[dict] = [
            {
                "role": "assistant",
                "agent": "work",
                "content": "Checking...",
                "tool_calls": [
                    {"name": "tool_a", "parameters": {"x": 1}},
                    {"name": "tool_b", "parameters": {"y": 2}},
                ],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "export.md"
            export_session_to_markdown(messages, dest)
            content = dest.read_text()
            assert "### Tool: tool_a" in content
            assert "### Tool: tool_b" in content


# ---------------------------------------------------------------------------
# StubGateway for integration tests — returns canned session data
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)

_SESSION_MESSAGES: list[dict] = [
    {"role": "user", "content": "What is the weather?"},
    {
        "role": "assistant",
        "agent": "homelab",
        "content": "Let me check.",
        "tool_calls": [{"name": "get_weather", "parameters": {"city": "NYC"}}],
    },
    {"role": "tool", "tool_name": "get_weather", "content": "Sunny, 72F"},
    {"role": "assistant", "agent": "homelab", "content": "It's sunny and 72F."},
]


class _StubGateway(GatewayProtocol):
    """Real GatewayProtocol implementation with canned data for export tests."""

    def __init__(self, messages: list[dict] | None = None) -> None:
        self._messages = messages if messages is not None else _SESSION_MESSAGES

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def send_message(self, text: str, *, session_id: str | None = None, requested_agent: str | None = None) -> None:
        pass

    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        pass

    async def cancel_run(self, run_id: str) -> None:
        pass

    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        return []

    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        return []

    async def memory_save(self, content: str, agent_name: str) -> str:
        return "stub-id"

    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        return True

    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        return []

    async def list_sessions(self) -> list[SessionSummary]:
        return []

    async def resume_session(self, session_id: str) -> SessionDetail:
        return SessionDetail(
            session_id=session_id,
            agent_name="homelab",
            summary="Weather check",
            started_at=_NOW,
            message_count=len(self._messages),
            agents_used=["homelab"],
            messages=list(self._messages),
        )

    async def list_agents(self) -> list[dict[str, Any]]:
        return [{"id": "homelab"}]

    async def list_models(self) -> list[dict[str, Any]]:
        return [{"id": "claude-sonnet-4-20250514"}]

    def on_event(self, callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]]) -> None:
        pass


def _make_app_with_gateway(gateway: _StubGateway) -> TuiApp:
    """Build a TuiApp wired to a stub gateway with a StringIO console."""
    app = TuiApp()
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    app.console = console
    app.renderer = ChatRenderer(console, app.theme)
    app.gateway = gateway
    app.session_manager = TuiSessionManager(gateway, app.agent_stack)
    app._output_buf = buf  # stash for assertions
    return app


# ---------------------------------------------------------------------------
# Integration tests for _handle_export_command wired into TuiApp
# ---------------------------------------------------------------------------


class TestHandleExportCommand:
    """Test _handle_export_command on a real TuiApp with real file I/O."""

    @pytest.mark.asyncio()
    async def test_export_writes_file_and_shows_success(self) -> None:
        """Calling /export with an active session writes the file and prints success."""
        gateway = _StubGateway()
        app = _make_app_with_gateway(gateway)
        # Create a session so current_session_id is set
        await app.session_manager.create("homelab")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test_export.md"
            await app._handle_export_command(str(dest))

            # File was created with correct content
            assert dest.exists()
            content = dest.read_text()
            assert "# Corvus Session Export" in content
            assert "What is the weather?" in content
            assert "## @homelab" in content
            assert "### Tool: get_weather" in content
            assert "Sunny, 72F" in content

            # Console shows success message
            rendered = app._output_buf.getvalue()
            assert "Session exported to" in rendered

    @pytest.mark.asyncio()
    async def test_export_no_active_session_shows_nothing_to_export(self) -> None:
        """When no session is active, export shows 'Nothing to export'."""
        gateway = _StubGateway()
        app = _make_app_with_gateway(gateway)
        # Do NOT create a session — current_session_id is None

        await app._handle_export_command(None)

        rendered = app._output_buf.getvalue()
        assert "Nothing to export" in rendered

    @pytest.mark.asyncio()
    async def test_export_empty_session_shows_nothing_to_export(self) -> None:
        """When session has no messages, export shows 'Nothing to export'."""
        gateway = _StubGateway(messages=[])
        app = _make_app_with_gateway(gateway)
        await app.session_manager.create("homelab")

        await app._handle_export_command(None)

        rendered = app._output_buf.getvalue()
        assert "Nothing to export" in rendered

    @pytest.mark.asyncio()
    async def test_export_default_path_when_no_args(self) -> None:
        """When no path arg given, export uses default ~/corvus-export-DATE.md."""
        gateway = _StubGateway()
        app = _make_app_with_gateway(gateway)
        await app.session_manager.create("homelab")

        # Call with no args — will write to home directory
        await app._handle_export_command(None)

        today = date.today().isoformat()
        default_path = Path.home() / f"corvus-export-{today}.md"

        rendered = app._output_buf.getvalue()
        # Either it succeeded (file created) or we see success message
        assert "Session exported to" in rendered
        assert today in rendered

        # Clean up
        if default_path.exists():
            default_path.unlink()
