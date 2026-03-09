"""Behavioral tests for TuiSessionManager.

Uses a real StubGateway implementation of GatewayProtocol — no mocks.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import pytest

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent

# ---------------------------------------------------------------------------
# StubGateway — real GatewayProtocol implementation with canned data
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 8, 14, 30, 0, tzinfo=UTC)

_CANNED_SESSIONS: list[SessionSummary] = [
    SessionSummary(
        session_id="aaaa1111-0000-0000-0000-000000000001",
        agent_name="work",
        summary="Fixed the deploy pipeline",
        started_at=_NOW,
        message_count=12,
        agents_used=["work"],
    ),
    SessionSummary(
        session_id="bbbb2222-0000-0000-0000-000000000002",
        agent_name="homelab",
        summary="Updated DNS records for tailnet",
        started_at=_NOW,
        message_count=5,
        agents_used=["homelab"],
    ),
    SessionSummary(
        session_id="cccc3333-0000-0000-0000-000000000003",
        agent_name="finance",
        summary="Reconciled March transactions",
        started_at=_NOW,
        message_count=8,
        agents_used=["finance"],
    ),
]


class StubGateway(GatewayProtocol):
    """Real implementation of GatewayProtocol for testing — returns canned data."""

    def __init__(self) -> None:
        self._sessions: list[SessionSummary] = list(_CANNED_SESSIONS)
        self._connected: bool = False
        self._resume_calls: list[str] = []

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

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
        return list(self._sessions)

    async def resume_session(self, session_id: str) -> SessionDetail:
        self._resume_calls.append(session_id)
        # Find matching session or fabricate one
        for s in self._sessions:
            if s.session_id == session_id:
                return SessionDetail(
                    session_id=s.session_id,
                    agent_name=s.agent_name,
                    summary=s.summary,
                    started_at=s.started_at,
                    message_count=s.message_count,
                    agents_used=s.agents_used,
                    messages=[
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi there"},
                    ],
                )
        # Unknown session — return detail with no agent
        return SessionDetail(
            session_id=session_id,
            agent_name="",
            summary="",
            started_at=None,
            message_count=0,
            agents_used=[],
            messages=[],
        )

    async def list_agents(self) -> list[dict[str, Any]]:
        return [{"name": "work"}, {"name": "homelab"}, {"name": "finance"}]

    async def list_models(self) -> list[dict[str, Any]]:
        return [{"id": "claude-sonnet-4-20250514"}]

    def on_event(
        self,
        callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]],
    ) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gateway() -> StubGateway:
    return StubGateway()


@pytest.fixture()
def agent_stack() -> AgentStack:
    return AgentStack()


@pytest.fixture()
def manager(gateway: StubGateway, agent_stack: AgentStack) -> TuiSessionManager:
    return TuiSessionManager(gateway=gateway, agent_stack=agent_stack)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for TuiSessionManager.create()."""

    @pytest.mark.asyncio()
    async def test_create_returns_session_id(self, manager: TuiSessionManager) -> None:
        session_id = await manager.create("work")
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID format

    @pytest.mark.asyncio()
    async def test_create_sets_current_session_id(
        self, manager: TuiSessionManager
    ) -> None:
        assert manager.current_session_id is None
        session_id = await manager.create("work")
        assert manager.current_session_id == session_id

    @pytest.mark.asyncio()
    async def test_create_pushes_agent_onto_stack(
        self, manager: TuiSessionManager, agent_stack: AgentStack
    ) -> None:
        session_id = await manager.create("work")
        assert agent_stack.depth == 1
        assert agent_stack.current.agent_name == "work"
        assert agent_stack.current.session_id == session_id

    @pytest.mark.asyncio()
    async def test_create_multiple_updates_current(
        self, manager: TuiSessionManager
    ) -> None:
        sid1 = await manager.create("work")
        sid2 = await manager.create("homelab")
        assert manager.current_session_id == sid2
        assert sid1 != sid2


class TestResume:
    """Tests for TuiSessionManager.resume()."""

    @pytest.mark.asyncio()
    async def test_resume_calls_gateway(
        self, manager: TuiSessionManager, gateway: StubGateway
    ) -> None:
        target_id = _CANNED_SESSIONS[0].session_id
        await manager.resume(target_id)
        assert target_id in gateway._resume_calls

    @pytest.mark.asyncio()
    async def test_resume_returns_session_detail(
        self, manager: TuiSessionManager
    ) -> None:
        target_id = _CANNED_SESSIONS[0].session_id
        detail = await manager.resume(target_id)
        assert isinstance(detail, SessionDetail)
        assert detail.session_id == target_id
        assert detail.agent_name == "work"
        assert len(detail.messages) == 2

    @pytest.mark.asyncio()
    async def test_resume_sets_current_session_id(
        self, manager: TuiSessionManager
    ) -> None:
        target_id = _CANNED_SESSIONS[1].session_id
        await manager.resume(target_id)
        assert manager.current_session_id == target_id

    @pytest.mark.asyncio()
    async def test_resume_restores_agent_stack(
        self, manager: TuiSessionManager, agent_stack: AgentStack
    ) -> None:
        target_id = _CANNED_SESSIONS[0].session_id
        await manager.resume(target_id)
        assert agent_stack.depth == 1
        assert agent_stack.current.agent_name == "work"
        assert agent_stack.current.session_id == target_id

    @pytest.mark.asyncio()
    async def test_resume_with_different_agent_switches_stack(
        self, manager: TuiSessionManager, agent_stack: AgentStack
    ) -> None:
        # First resume to "work"
        await manager.resume(_CANNED_SESSIONS[0].session_id)
        assert agent_stack.current.agent_name == "work"

        # Then resume to "homelab"
        await manager.resume(_CANNED_SESSIONS[1].session_id)
        assert agent_stack.current.agent_name == "homelab"
        assert agent_stack.depth == 1  # switch clears the stack

    @pytest.mark.asyncio()
    async def test_resume_unknown_session_no_agent_switch(
        self, manager: TuiSessionManager, agent_stack: AgentStack
    ) -> None:
        """When the gateway returns a session with no agent_name, the stack stays empty."""
        await manager.resume("unknown-session-id")
        assert manager.current_session_id == "unknown-session-id"
        assert agent_stack.depth == 0


class TestListSessions:
    """Tests for TuiSessionManager.list_sessions()."""

    @pytest.mark.asyncio()
    async def test_list_returns_all_sessions(
        self, manager: TuiSessionManager
    ) -> None:
        sessions = await manager.list_sessions()
        assert len(sessions) == 3

    @pytest.mark.asyncio()
    async def test_list_respects_limit(self, manager: TuiSessionManager) -> None:
        sessions = await manager.list_sessions(limit=2)
        assert len(sessions) == 2

    @pytest.mark.asyncio()
    async def test_list_limit_larger_than_count(
        self, manager: TuiSessionManager
    ) -> None:
        sessions = await manager.list_sessions(limit=100)
        assert len(sessions) == 3

    @pytest.mark.asyncio()
    async def test_list_returns_session_summary_objects(
        self, manager: TuiSessionManager
    ) -> None:
        sessions = await manager.list_sessions()
        for s in sessions:
            assert isinstance(s, SessionSummary)


class TestFormatSessionSummary:
    """Tests for TuiSessionManager.format_session_summary()."""

    def test_format_includes_all_fields(self, manager: TuiSessionManager) -> None:
        formatted = manager.format_session_summary(_CANNED_SESSIONS[0])
        assert "aaaa1111" in formatted
        assert "2026-03-08 14:30" in formatted
        assert "@work" in formatted
        assert "12 msgs" in formatted
        assert "Fixed the deploy pipeline" in formatted

    def test_format_no_summary(self, manager: TuiSessionManager) -> None:
        session = SessionSummary(
            session_id="dddd4444-0000-0000-0000-000000000004",
            agent_name="personal",
            summary="",
            started_at=_NOW,
            message_count=0,
        )
        formatted = manager.format_session_summary(session)
        assert "(no summary)" in formatted

    def test_format_no_started_at(self, manager: TuiSessionManager) -> None:
        session = SessionSummary(
            session_id="eeee5555-0000-0000-0000-000000000005",
            agent_name="work",
            summary="Something",
            started_at=None,
            message_count=3,
        )
        formatted = manager.format_session_summary(session)
        assert "unknown" in formatted

    def test_format_long_summary_truncated(self, manager: TuiSessionManager) -> None:
        long_summary = "A" * 100
        session = SessionSummary(
            session_id="ffff6666-0000-0000-0000-000000000006",
            agent_name="work",
            summary=long_summary,
            started_at=_NOW,
            message_count=1,
        )
        formatted = manager.format_session_summary(session)
        # The summary portion should be at most 50 chars
        assert "A" * 50 in formatted
        assert "A" * 51 not in formatted

    def test_format_no_agent_name(self, manager: TuiSessionManager) -> None:
        session = SessionSummary(
            session_id="gggg7777-0000-0000-0000-000000000007",
            agent_name="",
            summary="Test",
            started_at=_NOW,
            message_count=1,
        )
        formatted = manager.format_session_summary(session)
        assert "@unknown" in formatted


class TestMultipleOperations:
    """Tests that create/resume sequences correctly update state."""

    @pytest.mark.asyncio()
    async def test_create_then_resume_updates_session_id(
        self, manager: TuiSessionManager
    ) -> None:
        sid_created = await manager.create("work")
        assert manager.current_session_id == sid_created

        target = _CANNED_SESSIONS[1].session_id
        await manager.resume(target)
        assert manager.current_session_id == target
        assert manager.current_session_id != sid_created

    @pytest.mark.asyncio()
    async def test_resume_then_create_updates_session_id(
        self, manager: TuiSessionManager
    ) -> None:
        target = _CANNED_SESSIONS[0].session_id
        await manager.resume(target)
        assert manager.current_session_id == target

        sid_created = await manager.create("personal")
        assert manager.current_session_id == sid_created

    @pytest.mark.asyncio()
    async def test_initial_state_is_none(self, manager: TuiSessionManager) -> None:
        assert manager.current_session_id is None


class TestSearch:
    """Tests for TuiSessionManager.search()."""

    @pytest.mark.asyncio()
    async def test_search_matching_summary(self, manager: TuiSessionManager) -> None:
        """Search by a word in the summary returns the matching session."""
        results = await manager.search("deploy")
        assert len(results) == 1
        assert results[0].session_id == _CANNED_SESSIONS[0].session_id
        assert "deploy" in results[0].summary.lower()

    @pytest.mark.asyncio()
    async def test_search_no_match_returns_empty(self, manager: TuiSessionManager) -> None:
        """Search for a term that matches nothing returns an empty list."""
        results = await manager.search("nonexistent-query-xyz")
        assert results == []

    @pytest.mark.asyncio()
    async def test_search_is_case_insensitive(self, manager: TuiSessionManager) -> None:
        """Search should be case-insensitive for both summary and agent_name."""
        # "Fixed" appears with capital F in the canned data
        results_lower = await manager.search("fixed")
        results_upper = await manager.search("FIXED")
        results_mixed = await manager.search("FiXeD")
        assert len(results_lower) == 1
        assert len(results_upper) == 1
        assert len(results_mixed) == 1
        assert results_lower[0].session_id == results_upper[0].session_id == results_mixed[0].session_id

    @pytest.mark.asyncio()
    async def test_search_by_agent_name(self, manager: TuiSessionManager) -> None:
        """Search by agent_name returns sessions for that agent."""
        results = await manager.search("homelab")
        assert len(results) == 1
        assert results[0].agent_name == "homelab"
        assert results[0].session_id == _CANNED_SESSIONS[1].session_id

    @pytest.mark.asyncio()
    async def test_search_matches_multiple_sessions(self, manager: TuiSessionManager) -> None:
        """A broad query can match multiple sessions."""
        # All three canned sessions have agent_name containing lowercase letters;
        # search for a substring common in summaries
        results = await manager.search("the")
        # "Fixed the deploy pipeline" and "Reconciled March transactions" — only first has "the"
        matching_ids = {r.session_id for r in results}
        assert _CANNED_SESSIONS[0].session_id in matching_ids  # "Fixed the deploy pipeline"
