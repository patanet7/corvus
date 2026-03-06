"""SQLite integration tests — full lifecycle with real DB.

Verifies: create session → add messages → create dispatch → start runs →
add events → query back → verify contracts.
"""

from datetime import UTC, datetime
from pathlib import Path

from corvus.session_manager import SessionManager


class TestSessionLifecycle:
    def test_full_session_lifecycle(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")

        # Create session
        mgr.start("sess-1", user="testuser")

        # Add messages (agent/model are keyword-only)
        mgr.add_message("sess-1", "user", "Hello", agent="general")
        mgr.add_message("sess-1", "assistant", "Hi there", agent="general", model="sonnet")

        # Create a dispatch (required FK parent for agent_runs)
        mgr.create_dispatch(
            "d-1",
            session_id="sess-1",
            user="testuser",
            prompt="Check finances",
            dispatch_mode="single",
            target_agents=["finance"],
            turn_id="t-1",
        )

        # Start a run
        mgr.start_agent_run(
            "run-1",
            dispatch_id="d-1",
            session_id="sess-1",
            agent="finance",
            turn_id="t-1",
            backend="claude",
            model="sonnet",
        )

        # Add run events
        mgr.add_run_event(
            "run-1",
            dispatch_id="d-1",
            session_id="sess-1",
            event_type="run_output_chunk",
            payload={"content": "test", "chunk_index": 0},
        )

        # Complete the run
        mgr.update_agent_run(
            "run-1",
            status="done",
            summary="Completed",
            cost_usd=0.01,
            tokens_used=500,
            completed_at=datetime.now(UTC),
        )

        # Query back and verify
        session = mgr.get("sess-1")
        assert session is not None
        assert session["user"] == "testuser"

        messages = mgr.list_messages("sess-1", limit=10)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"

        run = mgr.get_run("run-1")
        assert run is not None
        assert run["status"] == "done"
        assert run["agent"] == "finance"

        events = mgr.list_run_events("run-1", limit=10)
        assert len(events) >= 1
        assert events[0]["event_type"] == "run_output_chunk"

    def test_multiple_sessions_isolated(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        mgr.start("sess-1", user="user1")
        mgr.start("sess-2", user="user2")
        mgr.add_message("sess-1", "user", "Hello from sess-1")
        mgr.add_message("sess-2", "user", "Hello from sess-2")

        msgs1 = mgr.list_messages("sess-1", limit=10)
        msgs2 = mgr.list_messages("sess-2", limit=10)
        assert len(msgs1) == 1
        assert len(msgs2) == 1
        assert msgs1[0]["content"] == "Hello from sess-1"
        assert msgs2[0]["content"] == "Hello from sess-2"

    def test_run_events_isolated_by_run_id(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        mgr.start("sess-1", user="testuser")

        # Create dispatch (FK parent for runs)
        mgr.create_dispatch(
            "d-1",
            session_id="sess-1",
            user="testuser",
            prompt="Multi-agent task",
            dispatch_mode="parallel",
            target_agents=["finance", "docs"],
            turn_id="t-1",
        )

        mgr.start_agent_run(
            "run-1",
            dispatch_id="d-1",
            session_id="sess-1",
            agent="finance",
            turn_id="t-1",
        )
        mgr.start_agent_run(
            "run-2",
            dispatch_id="d-1",
            session_id="sess-1",
            agent="docs",
            turn_id="t-1",
        )

        mgr.add_run_event(
            "run-1",
            dispatch_id="d-1",
            session_id="sess-1",
            event_type="tool_start",
            payload={"tool": "read"},
        )
        mgr.add_run_event(
            "run-2",
            dispatch_id="d-1",
            session_id="sess-1",
            event_type="tool_start",
            payload={"tool": "write"},
        )

        events1 = mgr.list_run_events("run-1", limit=10)
        events2 = mgr.list_run_events("run-2", limit=10)
        assert len(events1) == 1
        assert len(events2) == 1
        assert events1[0]["payload"]["tool"] == "read"
        assert events2[0]["payload"]["tool"] == "write"

    def test_session_events_persisted_and_queryable(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        mgr.start("sess-1", user="testuser")

        mgr.add_event(
            "sess-1",
            "dispatch_start",
            {"dispatch_id": "d-1"},
            turn_id="t-1",
        )
        mgr.add_event(
            "sess-1",
            "run_start",
            {"run_id": "r-1"},
            turn_id="t-1",
        )

        events = mgr.list_events("sess-1", limit=10)
        assert len(events) == 2
        types = [e["event_type"] for e in events]
        assert "dispatch_start" in types
        assert "run_start" in types

    def test_dispatch_lifecycle(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        mgr.start("sess-1", user="testuser")

        mgr.create_dispatch(
            "d-1",
            session_id="sess-1",
            user="testuser",
            prompt="Hello",
            dispatch_mode="single",
            target_agents=["work"],
        )

        dispatch = mgr.get_dispatch("d-1")
        assert dispatch is not None
        assert dispatch["status"] == "queued"
        assert dispatch["session_id"] == "sess-1"

        mgr.update_dispatch("d-1", status="done", completed_at=datetime.now(UTC))
        dispatch = mgr.get_dispatch("d-1")
        assert dispatch["status"] == "done"
        assert dispatch["completed_at"] is not None

    def test_session_end_updates_metadata(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        mgr.start("sess-1", user="testuser")

        mgr.end(
            "sess-1",
            ended_at=datetime.now(UTC),
            summary="Test session completed",
            message_count=5,
            tool_count=2,
            agents_used=["work", "finance"],
        )

        session = mgr.get("sess-1")
        assert session is not None
        assert session["summary"] == "Test session completed"
        assert session["message_count"] == 5
        assert session["tool_count"] == 2

    def test_session_delete_cascades(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        mgr.start("sess-1", user="testuser")
        mgr.add_message("sess-1", "user", "Hello")
        mgr.add_event("sess-1", "ping", {"ok": True})

        mgr.delete("sess-1")

        assert mgr.get("sess-1") is None
        assert mgr.list_messages("sess-1") == []
        assert mgr.list_events("sess-1") == []
