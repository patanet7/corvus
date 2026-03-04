"""Behavioral tests for claw.session_manager -- standalone session CRUD.

All tests are behavioral: real SQLite databases, real objects.
NO mocks, NO monkeypatch, NO @patch.
"""

import pytest

from corvus.session_manager import SessionManager


class TestSessionManager:
    """Tests for SessionManager extracted from MemoryEngine."""

    @pytest.fixture()
    def manager(self, tmp_path):
        return SessionManager(db_path=tmp_path / "sessions.sqlite")

    def test_start_and_get_session(self, manager):
        manager.start("s1", user="thomas", agent_name="personal")
        session = manager.get("s1")
        assert session is not None
        assert session["id"] == "s1"
        assert session["user"] == "thomas"

    def test_end_session(self, manager):
        manager.start("s2", user="thomas", agent_name="work")
        manager.end("s2", message_count=5, tool_count=3, agents_used=["work", "personal"])
        session = manager.get("s2")
        assert session["ended_at"] is not None
        assert session["message_count"] == 5
        assert session["tool_count"] == 3
        assert session["agents_used"] == ["work", "personal"]

    def test_list_sessions(self, manager):
        for i in range(3):
            manager.start(f"s-{i}", user="thomas", agent_name="personal")
        sessions = manager.list(limit=10)
        assert len(sessions) == 3

    def test_delete_session(self, manager):
        manager.start("del-me", user="thomas", agent_name="personal")
        manager.delete("del-me")
        assert manager.get("del-me") is None

    def test_rename_session(self, manager):
        manager.start("rename-me", user="thomas", agent_name="personal")
        manager.rename("rename-me", "New Title")
        session = manager.get("rename-me")
        assert session["summary"] == "New Title"

    def test_list_with_user_filter(self, manager):
        manager.start("s-1", user="thomas", agent_name="personal")
        manager.start("s-2", user="other", agent_name="work")
        sessions = manager.list(user="thomas")
        assert len(sessions) == 1
        assert sessions[0]["user"] == "thomas"

    def test_list_with_agent_filter(self, manager):
        manager.start("s-1", user="thomas", agent_name="personal")
        manager.end("s-1", agents_used=["personal"])
        manager.start("s-2", user="thomas", agent_name="work")
        manager.end("s-2", agents_used=["work", "homelab"])
        sessions = manager.list(agent_filter="homelab")
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s-2"

    def test_list_with_offset(self, manager):
        for i in range(5):
            manager.start(f"s-{i}", user="thomas", agent_name="personal")
        sessions = manager.list(limit=2, offset=2)
        assert len(sessions) == 2

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get("nonexistent") is None

    def test_session_to_markdown(self, manager):
        manager.start("md-1", user="thomas", agent_name="personal")
        manager.end("md-1", message_count=3, tool_count=1, agents_used=["personal"])
        session = manager.get("md-1")
        md = manager.session_to_markdown(session)
        assert isinstance(md, str)
        assert "md-1" in md
        assert "thomas" in md
        assert "personal" in md

    def test_session_to_markdown_no_summary(self, manager):
        manager.start("md-2", user="thomas", agent_name="work")
        session = manager.get("md-2")
        md = manager.session_to_markdown(session)
        assert "Session md-2" in md

    def test_start_stores_agent_name(self, manager):
        manager.start("agent-1", user="thomas", agent_name="homelab")
        session = manager.get("agent-1")
        assert session["agent_name"] == "homelab"

    def test_started_at_is_set_automatically(self, manager):
        manager.start("auto-ts", user="thomas", agent_name="personal")
        session = manager.get("auto-ts")
        assert session["started_at"] is not None
        assert len(session["started_at"]) > 0

    def test_delete_nonexistent_is_noop(self, manager):
        """Deleting a session that doesn't exist should not raise."""
        manager.delete("does-not-exist")

    def test_rename_nonexistent_is_noop(self, manager):
        """Renaming a session that doesn't exist should not raise."""
        manager.rename("does-not-exist", "New Name")

    def test_add_and_list_messages(self, manager):
        manager.start("msg-1", user="thomas", agent_name="personal")
        manager.add_message("msg-1", "user", "hello", agent="personal", model="sonnet")
        manager.add_message("msg-1", "assistant", "hi there", agent="personal", model="sonnet")
        messages = manager.list_messages("msg-1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "hi there"

    def test_delete_session_cascades_messages(self, manager):
        manager.start("msg-del", user="thomas", agent_name="work")
        manager.add_message("msg-del", "user", "check logs", agent="work", model="sonnet")
        assert len(manager.list_messages("msg-del")) == 1
        manager.delete("msg-del")
        assert manager.get("msg-del") is None
        assert manager.list_messages("msg-del") == []

    def test_session_to_markdown_includes_transcript_when_provided(self, manager):
        manager.start("md-3", user="thomas", agent_name="homelab")
        manager.end("md-3", message_count=2, tool_count=0, agents_used=["homelab"])
        manager.add_message("md-3", "user", "is plex up?", agent="homelab", model="sonnet")
        manager.add_message("md-3", "assistant", "yes", agent="homelab", model="sonnet")
        session = manager.get("md-3")
        messages = manager.list_messages("md-3")
        md = manager.session_to_markdown(session, messages)
        assert "## Transcript" in md
        assert "is plex up?" in md
        assert "yes" in md

    def test_add_and_list_session_events(self, manager):
        manager.start("evt-1", user="thomas", agent_name="work")
        manager.add_event(
            "evt-1",
            "task_start",
            {"type": "task_start", "task_id": "task-1", "agent": "work"},
            turn_id="turn-1",
        )
        manager.add_event(
            "evt-1",
            "task_complete",
            {"type": "task_complete", "task_id": "task-1", "result": "success"},
            turn_id="turn-1",
        )
        events = manager.list_events("evt-1")
        assert len(events) == 2
        assert events[0]["event_type"] == "task_start"
        assert events[0]["turn_id"] == "turn-1"
        assert events[1]["payload"]["type"] == "task_complete"

    def test_list_events_filters_by_type(self, manager):
        manager.start("evt-2", user="thomas", agent_name="work")
        manager.add_event("evt-2", "task_start", {"type": "task_start", "task_id": "a"})
        manager.add_event("evt-2", "tool_start", {"type": "tool_start", "tool": "Bash"})
        filtered = manager.list_events("evt-2", event_types=["tool_start"])
        assert len(filtered) == 1
        assert filtered[0]["event_type"] == "tool_start"

    def test_delete_session_cascades_events(self, manager):
        manager.start("evt-del", user="thomas", agent_name="finance")
        manager.add_event("evt-del", "task_start", {"type": "task_start", "task_id": "x"})
        assert len(manager.list_events("evt-del")) == 1
        manager.delete("evt-del")
        assert manager.list_events("evt-del") == []

    def test_start_agent_run_persists_route_metadata(self, manager):
        manager.start("sess-route-1", user="thomas", agent_name="work")
        manager.create_dispatch(
            "disp-route-1",
            session_id="sess-route-1",
            user="thomas",
            prompt="Refactor backend service",
            dispatch_mode="parallel",
            target_agents=["work", "docs"],
            status="running",
        )
        manager.start_agent_run(
            "run-route-1",
            dispatch_id="disp-route-1",
            session_id="sess-route-1",
            agent="work",
            backend="claude",
            model="sonnet",
            task_type="coding",
            subtask_id="implementation",
            skill="data-transform",
            status="executing",
        )

        run = manager.get_run("run-route-1")
        assert run is not None
        assert run["task_type"] == "coding"
        assert run["subtask_id"] == "implementation"
        assert run["skill"] == "data-transform"

    def test_list_runs_includes_route_metadata(self, manager):
        manager.start("sess-route-2", user="thomas", agent_name="docs")
        manager.create_dispatch(
            "disp-route-2",
            session_id="sess-route-2",
            user="thomas",
            prompt="Produce release notes",
            dispatch_mode="direct",
            target_agents=["docs"],
            status="running",
        )
        manager.start_agent_run(
            "run-route-2",
            dispatch_id="disp-route-2",
            session_id="sess-route-2",
            agent="docs",
            backend="claude",
            model="opus",
            task_type="coding",
            subtask_id="review",
            skill="code-review",
            status="planning",
        )

        runs = manager.list_runs(user="thomas")
        row = next((run for run in runs if run["id"] == "run-route-2"), None)
        assert row is not None
        assert row["task_type"] == "coding"
        assert row["subtask_id"] == "review"
        assert row["skill"] == "code-review"

    def test_list_dispatch_events_returns_run_events(self, manager):
        manager.start("sess-disp-events-1", user="thomas", agent_name="work")
        manager.create_dispatch(
            "disp-events-1",
            session_id="sess-disp-events-1",
            user="thomas",
            prompt="Run replay test",
            dispatch_mode="direct",
            target_agents=["work"],
            status="running",
        )
        manager.start_agent_run(
            "run-events-1",
            dispatch_id="disp-events-1",
            session_id="sess-disp-events-1",
            agent="work",
            status="executing",
        )
        manager.add_run_event(
            "run-events-1",
            dispatch_id="disp-events-1",
            session_id="sess-disp-events-1",
            event_type="run_phase",
            payload={"type": "run_phase", "phase": "executing", "summary": "working"},
            turn_id="turn-events-1",
        )

        rows = manager.list_dispatch_events("disp-events-1")
        assert len(rows) == 1
        assert rows[0]["event_type"] == "run_phase"
        assert rows[0]["dispatch_id"] == "disp-events-1"
        assert rows[0]["run_id"] == "run-events-1"

    def test_add_and_list_trace_events(self, manager):
        manager.start("sess-trace-1", user="thomas", agent_name="work")
        manager.create_dispatch(
            "disp-trace-1",
            session_id="sess-trace-1",
            user="thomas",
            prompt="Trace test",
            dispatch_mode="direct",
            target_agents=["work"],
            status="running",
        )
        manager.start_agent_run(
            "run-trace-1",
            dispatch_id="disp-trace-1",
            session_id="sess-trace-1",
            agent="work",
            status="executing",
        )
        inserted = manager.add_trace_event(
            source_app="work",
            session_id="sess-trace-1",
            dispatch_id="disp-trace-1",
            run_id="run-trace-1",
            turn_id="turn-trace-1",
            hook_event_type="run_phase",
            payload={"phase": "executing", "summary": "Streaming output"},
            summary="Streaming output",
            model_name="ollama:qwen3:8b",
        )
        assert inserted["hook_event_type"] == "run_phase"
        assert inserted["source_app"] == "work"
        assert inserted["model_name"] == "ollama:qwen3:8b"

        rows = manager.list_trace_events(user="thomas", hook_event_types=["run_phase"])
        assert len(rows) == 1
        assert rows[0]["id"] == inserted["id"]

        one = manager.get_trace_event(inserted["id"], user="thomas")
        assert one is not None
        assert one["session_id"] == "sess-trace-1"
        assert one["payload"]["phase"] == "executing"

    def test_trace_events_are_user_scoped(self, manager):
        manager.start("sess-trace-u1", user="thomas", agent_name="work")
        manager.start("sess-trace-u2", user="other", agent_name="work")
        manager.add_trace_event(
            source_app="work",
            session_id="sess-trace-u1",
            hook_event_type="dispatch_start",
            payload={"dispatch_id": "disp-u1"},
        )
        manager.add_trace_event(
            source_app="work",
            session_id="sess-trace-u2",
            hook_event_type="dispatch_start",
            payload={"dispatch_id": "disp-u2"},
        )

        thomas_rows = manager.list_trace_events(user="thomas")
        assert len(thomas_rows) == 1
        assert thomas_rows[0]["session_id"] == "sess-trace-u1"

        other_rows = manager.list_trace_events(user="other")
        assert len(other_rows) == 1
        assert other_rows[0]["session_id"] == "sess-trace-u2"

    def test_trace_filter_options(self, manager):
        manager.start("sess-trace-opt", user="thomas", agent_name="general")
        manager.add_trace_event(
            source_app="router",
            session_id="sess-trace-opt",
            hook_event_type="dispatch_plan",
            payload={"strategy": "parallel"},
        )
        options = manager.get_trace_filter_options(user="thomas")
        assert "router" in options["source_apps"]
        assert "sess-trace-opt" in options["session_ids"]
        assert "dispatch_plan" in options["hook_event_types"]
