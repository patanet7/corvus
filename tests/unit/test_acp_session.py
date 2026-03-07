"""Behavioral tests for AcpSessionTracker — no mocks."""

from datetime import datetime

from corvus.acp.session import AcpSessionState, AcpSessionTracker


def test_create_session() -> None:
    tracker = AcpSessionTracker()
    state = tracker.create(
        corvus_run_id="run-1",
        corvus_session_id="sess-A",
        acp_agent="codex",
        parent_agent="huginn",
        process_pid=12345,
    )
    assert isinstance(state, AcpSessionState)
    assert state.corvus_run_id == "run-1"
    assert state.corvus_session_id == "sess-A"
    assert state.acp_agent == "codex"
    assert state.parent_agent == "huginn"
    assert state.process_pid == 12345
    assert state.acp_session_id is None
    assert state.status == "uninitialized"
    assert isinstance(state.created_at, datetime)
    assert state.created_at.tzinfo is not None
    assert state.last_prompt_at is None
    assert state.total_turns == 0


def test_get_session() -> None:
    tracker = AcpSessionTracker()
    tracker.create(
        corvus_run_id="run-2",
        corvus_session_id="sess-A",
        acp_agent="gemini",
        parent_agent="huginn",
        process_pid=22222,
    )
    result = tracker.get("run-2")
    assert result is not None
    assert result.corvus_run_id == "run-2"
    assert result.acp_agent == "gemini"


def test_get_missing_session() -> None:
    tracker = AcpSessionTracker()
    assert tracker.get("nonexistent") is None


def test_update_status() -> None:
    tracker = AcpSessionTracker()
    tracker.create(
        corvus_run_id="run-3",
        corvus_session_id="sess-A",
        acp_agent="opencode",
        parent_agent="huginn",
        process_pid=33333,
    )
    tracker.update_status("run-3", "ready")
    state = tracker.get("run-3")
    assert state is not None
    assert state.status == "ready"


def test_set_acp_session_id() -> None:
    tracker = AcpSessionTracker()
    tracker.create(
        corvus_run_id="run-4",
        corvus_session_id="sess-B",
        acp_agent="codex",
        parent_agent="huginn",
        process_pid=44444,
    )
    tracker.set_acp_session_id("run-4", "acp-uuid-1234")
    state = tracker.get("run-4")
    assert state is not None
    assert state.acp_session_id == "acp-uuid-1234"


def test_remove_session() -> None:
    tracker = AcpSessionTracker()
    tracker.create(
        corvus_run_id="run-5",
        corvus_session_id="sess-A",
        acp_agent="codex",
        parent_agent="huginn",
        process_pid=55555,
    )
    tracker.remove("run-5")
    assert tracker.get("run-5") is None


def test_list_by_corvus_session() -> None:
    tracker = AcpSessionTracker()
    tracker.create(
        corvus_run_id="run-a1",
        corvus_session_id="sess_A",
        acp_agent="codex",
        parent_agent="huginn",
        process_pid=10001,
    )
    tracker.create(
        corvus_run_id="run-a2",
        corvus_session_id="sess_A",
        acp_agent="gemini",
        parent_agent="huginn",
        process_pid=10002,
    )
    tracker.create(
        corvus_run_id="run-b1",
        corvus_session_id="sess_B",
        acp_agent="opencode",
        parent_agent="huginn",
        process_pid=10003,
    )
    results = tracker.list_by_session("sess_A")
    assert len(results) == 2
    run_ids = {s.corvus_run_id for s in results}
    assert run_ids == {"run-a1", "run-a2"}
