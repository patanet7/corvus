"""Behavioral tests for session domain service helpers."""

from __future__ import annotations

from corvus.session_manager import SessionManager
from corvus.sessions.service import SessionService


class TestSessionService:
    def test_user_scoped_session_dispatch_run_access(self, tmp_path) -> None:
        session_mgr = SessionManager(db_path=tmp_path / "sessions.sqlite")
        service = SessionService(session_mgr)

        session_mgr.start("sess-1", user="alice", agent_name="general")
        session_mgr.start("sess-2", user="bob", agent_name="general")

        session_mgr.create_dispatch(
            "disp-1",
            session_id="sess-1",
            user="alice",
            prompt="check logs",
            dispatch_mode="direct",
            target_agents=["general"],
        )
        session_mgr.start_agent_run(
            "run-1",
            dispatch_id="disp-1",
            session_id="sess-1",
            agent="general",
            status="executing",
        )

        alice_session = service.get_user_session("sess-1", user="alice")
        assert alice_session is not None
        assert alice_session["id"] == "sess-1"

        assert service.get_user_session("sess-1", user="bob") is None
        assert service.get_user_dispatch("disp-1", user="alice") is not None
        assert service.get_user_dispatch("disp-1", user="bob") is None
        assert service.get_user_run("run-1", user="alice") is not None
        assert service.get_user_run("run-1", user="bob") is None

    def test_session_export_and_delete_are_user_scoped(self, tmp_path) -> None:
        session_mgr = SessionManager(db_path=tmp_path / "sessions.sqlite")
        service = SessionService(session_mgr)

        session_mgr.start("sess-exp", user="alice", agent_name="general")
        session_mgr.add_message(
            "sess-exp",
            "user",
            "hello world",
            agent="general",
            model="claude/sonnet",
        )

        markdown = service.export_user_session_markdown("sess-exp", user="alice")
        assert markdown is not None
        assert "hello world" in markdown

        assert service.export_user_session_markdown("sess-exp", user="bob") is None
        assert service.delete_user_session("sess-exp", user="bob") is False
        assert service.delete_user_session("sess-exp", user="alice") is True
        assert session_mgr.get("sess-exp") is None
