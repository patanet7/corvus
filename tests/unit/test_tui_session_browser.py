"""Tests for Task 4.3: Session Browser — Rich table, search, resume.

NO MOCKS — uses real renderer with StringIO, real SessionSummary objects.
"""

import io
from datetime import UTC, datetime

from rich.console import Console

from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import SessionSummary
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


def _make_sessions() -> list[SessionSummary]:
    return [
        SessionSummary(
            session_id="aaaa-1111-bbbb-2222",
            agent_name="homelab",
            summary="Fixed nginx configuration",
            started_at=datetime(2026, 3, 8, 14, 30, tzinfo=UTC),
            message_count=12,
            agents_used=["homelab"],
        ),
        SessionSummary(
            session_id="cccc-3333-dddd-4444",
            agent_name="finance",
            summary="Budget review Q1",
            started_at=datetime(2026, 3, 7, 10, 0, tzinfo=UTC),
            message_count=5,
            agents_used=["finance"],
        ),
        SessionSummary(
            session_id="eeee-5555-ffff-6666",
            agent_name="work",
            summary="Deploy pipeline debugging",
            started_at=datetime(2026, 3, 6, 9, 15, tzinfo=UTC),
            message_count=24,
            agents_used=["work", "homelab"],
        ),
    ]


class TestRenderSessionsTable:
    """render_sessions_table displays sessions as a Rich table."""

    def test_shows_session_ids(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        assert "aaaa-111" in output
        assert "cccc-333" in output

    def test_shows_agent_names(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        assert "@homelab" in output
        assert "@finance" in output
        assert "@work" in output

    def test_shows_message_counts(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        assert "12" in output
        assert "24" in output

    def test_shows_summaries(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        assert "Fixed nginx" in output
        assert "Budget review" in output

    def test_shows_timestamps(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        assert "2026-03-08" in output

    def test_empty_sessions(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_sessions_table([])
        output = _output(buf)
        assert "No sessions" in output

    def test_custom_title(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()[:1]
        renderer.render_sessions_table(sessions, title="Search Results")
        output = _output(buf)
        assert "Search Results" in output

    def test_no_summary_shows_placeholder(self) -> None:
        renderer, buf = _make_renderer()
        sessions = [SessionSummary(session_id="xxxx-yyyy", agent_name="huginn")]
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        assert "no summary" in output

    def test_table_header(self) -> None:
        renderer, buf = _make_renderer()
        sessions = _make_sessions()
        renderer.render_sessions_table(sessions)
        output = _output(buf)
        # Table should have Sessions title by default
        assert "Sessions" in output
