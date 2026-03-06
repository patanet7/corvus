"""Behavioral tests for SessionEmitter — send/persist/trace delegation.

Verifies that SessionEmitter correctly persists session events, run events,
and publishes traces. Uses real SQLite DB, no mocks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from corvus.gateway.trace_hub import TraceHub
from corvus.session_manager import SessionManager
from tests.conftest import run


class _MinimalRuntime:
    """Real runtime with only session_mgr and trace_hub.

    Provides the subset of GatewayRuntime that SessionEmitter needs:
    ``session_mgr`` for persistence and ``trace_hub`` for live fan-out.
    """

    def __init__(self, db_path: Path) -> None:
        self.session_mgr = SessionManager(db_path=db_path)
        self.trace_hub = TraceHub()


def _make_runtime(tmp_path: Path) -> _MinimalRuntime:
    """Create a minimal runtime rooted at *tmp_path*."""
    db = tmp_path / "sessions.sqlite"
    return _MinimalRuntime(db_path=db)


def _seed_session(runtime: _MinimalRuntime, session_id: str, user: str) -> None:
    """Start a session so foreign-key constraints are satisfied."""
    runtime.session_mgr.start(session_id, user=user)


def _seed_dispatch_and_run(
    runtime: _MinimalRuntime,
    *,
    session_id: str,
    dispatch_id: str,
    run_id: str,
    user: str,
    agent: str = "test-agent",
) -> None:
    """Create a dispatch + run so run-event persistence succeeds."""
    runtime.session_mgr.create_dispatch(
        dispatch_id,
        session_id=session_id,
        user=user,
        prompt="test prompt",
        dispatch_mode="single",
        target_agents=[agent],
    )
    runtime.session_mgr.start_agent_run(
        run_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        agent=agent,
    )


# ---------------------------------------------------------------------------
# TestSessionEmitterSend
# ---------------------------------------------------------------------------


class TestSessionEmitterSend:
    """SessionEmitter.send() persists events and publishes traces."""

    def test_send_persists_session_event(self, tmp_path: Path) -> None:
        """send() with persist=True stores the event via add_event."""
        from corvus.gateway.session_emitter import SessionEmitter

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        user = "alice"
        _seed_session(rt, session_id, user)

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        payload = {
            "type": "dispatch_start",
            "dispatch_id": str(uuid4()),
            "session_id": session_id,
            "message": "hello",
        }

        run(emitter.send(payload, persist=True))

        events = rt.session_mgr.list_events(session_id)
        assert len(events) >= 1, "Expected at least one session event persisted"
        stored = events[0]
        assert stored["event_type"] == "dispatch_start"

    def test_send_persists_run_event(self, tmp_path: Path) -> None:
        """send() with persist=True + run_id + dispatch_id stores run event."""
        from corvus.gateway.session_emitter import SessionEmitter

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        dispatch_id = str(uuid4())
        run_id = str(uuid4())
        user = "bob"
        _seed_session(rt, session_id, user)
        _seed_dispatch_and_run(
            rt,
            session_id=session_id,
            dispatch_id=dispatch_id,
            run_id=run_id,
            user=user,
        )

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        payload = {
            "type": "run_start",
            "dispatch_id": dispatch_id,
            "run_id": run_id,
            "session_id": session_id,
            "agent": "test-agent",
        }

        run(
            emitter.send(
                payload,
                persist=True,
                run_id=run_id,
                dispatch_id=dispatch_id,
            )
        )

        run_events = rt.session_mgr.list_run_events(run_id)
        assert len(run_events) >= 1, "Expected at least one run event persisted"
        stored = run_events[0]
        assert stored["event_type"] == "run_start"

    def test_send_without_persist_does_not_store(self, tmp_path: Path) -> None:
        """send() without persist=True must NOT store any events."""
        from corvus.gateway.session_emitter import SessionEmitter

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        user = "carol"
        _seed_session(rt, session_id, user)

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        payload = {
            "type": "dispatch_start",
            "dispatch_id": str(uuid4()),
            "session_id": session_id,
            "message": "ephemeral",
        }

        run(emitter.send(payload, persist=False))

        events = rt.session_mgr.list_events(session_id)
        assert len(events) == 0, "No events should be persisted when persist=False"

    def test_send_publishes_trace_for_traced_event(self, tmp_path: Path) -> None:
        """send() publishes trace events to TraceHub for traceable types."""
        from corvus.gateway.session_emitter import SessionEmitter

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        user = "dave"
        _seed_session(rt, session_id, user)

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        # Subscribe to trace hub before sending
        queue = rt.trace_hub.subscribe()

        payload = {
            "type": "dispatch_start",
            "dispatch_id": str(uuid4()),
            "session_id": session_id,
            "message": "traced event",
        }

        run(emitter.send(payload, persist=True))

        # Check that trace hub received the event
        assert not queue.empty(), "TraceHub should have received a trace event"
        envelope = queue.get_nowait()
        assert envelope.user == user
        assert envelope.event["hook_event_type"] == "dispatch_start"


# ---------------------------------------------------------------------------
# TestSessionEmitterPhases
# ---------------------------------------------------------------------------


class TestSessionEmitterPhases:
    """Phase emission helpers work correctly."""

    def test_emit_phase_sends_run_phase_event(self, tmp_path: Path) -> None:
        """emit_phase() emits a run_phase event that is persisted."""
        from corvus.gateway.session_emitter import SessionEmitter
        from corvus.gateway.chat_session import TurnContext

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        dispatch_id = str(uuid4())
        run_id = str(uuid4())
        turn_id = str(uuid4())
        user = "eve"
        agent = "test-agent"

        _seed_session(rt, session_id, user)
        _seed_dispatch_and_run(
            rt,
            session_id=session_id,
            dispatch_id=dispatch_id,
            run_id=run_id,
            user=user,
            agent=agent,
        )

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        turn = TurnContext(
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=True,
        )

        run(
            emitter.emit_phase(
                turn,
                run_id=run_id,
                task_id="task-1",
                agent=agent,
                route_payload={},
                phase="routing",
                summary="Routing and model validation",
            )
        )

        # run_phase should appear in both session events and run events
        session_events = rt.session_mgr.list_events(session_id)
        phase_events = [e for e in session_events if e["event_type"] == "run_phase"]
        assert len(phase_events) >= 1, "Expected at least one run_phase session event"

        run_events = rt.session_mgr.list_run_events(run_id)
        run_phase_events = [e for e in run_events if e["event_type"] == "run_phase"]
        assert len(run_phase_events) >= 1, "Expected at least one run_phase run event"

    def test_emit_phase_sends_task_progress_for_active_phases(self, tmp_path: Path) -> None:
        """emit_phase() also emits task_progress for non-terminal phases."""
        from corvus.gateway.session_emitter import SessionEmitter
        from corvus.gateway.chat_session import TurnContext

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        dispatch_id = str(uuid4())
        run_id = str(uuid4())
        turn_id = str(uuid4())
        user = "frank"
        agent = "test-agent"

        _seed_session(rt, session_id, user)
        _seed_dispatch_and_run(
            rt,
            session_id=session_id,
            dispatch_id=dispatch_id,
            run_id=run_id,
            user=user,
            agent=agent,
        )

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        turn = TurnContext(
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=True,
        )

        # "executing" is a non-terminal phase, so it should produce both
        # run_phase AND task_progress events
        run(
            emitter.emit_phase(
                turn,
                run_id=run_id,
                task_id="task-1",
                agent=agent,
                route_payload={},
                phase="executing",
                summary="Agent execution started",
            )
        )

        session_events = rt.session_mgr.list_events(session_id)
        event_types = [e["event_type"] for e in session_events]
        assert "run_phase" in event_types, "Expected run_phase event"
        assert "task_progress" in event_types, "Expected task_progress event for active phase"

    def test_emit_phase_skips_task_progress_for_terminal_phases(self, tmp_path: Path) -> None:
        """emit_phase() does NOT emit task_progress for done/error/interrupted."""
        from corvus.gateway.session_emitter import SessionEmitter
        from corvus.gateway.chat_session import TurnContext

        rt = _make_runtime(tmp_path)
        session_id = str(uuid4())
        dispatch_id = str(uuid4())
        run_id = str(uuid4())
        turn_id = str(uuid4())
        user = "grace"
        agent = "test-agent"

        _seed_session(rt, session_id, user)
        _seed_dispatch_and_run(
            rt,
            session_id=session_id,
            dispatch_id=dispatch_id,
            run_id=run_id,
            user=user,
            agent=agent,
        )

        emitter = SessionEmitter(
            runtime=rt,
            user=user,
            session_id=session_id,
            ws_send=None,
        )

        turn = TurnContext(
            dispatch_id=dispatch_id,
            turn_id=turn_id,
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=True,
        )

        # "done" is a terminal phase — should only produce run_phase, not task_progress
        run(
            emitter.emit_phase(
                turn,
                run_id=run_id,
                task_id="task-1",
                agent=agent,
                route_payload={},
                phase="done",
                summary="Completed",
            )
        )

        session_events = rt.session_mgr.list_events(session_id)
        event_types = [e["event_type"] for e in session_events]
        assert "run_phase" in event_types, "Expected run_phase event even for terminal phase"
        assert "task_progress" not in event_types, "task_progress should NOT appear for terminal phase"
