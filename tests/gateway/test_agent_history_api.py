"""Behavioral test for agent history query via SessionManager."""

from pathlib import Path

from corvus.session_manager import SessionManager


class TestAgentHistoryQuery:
    """Verify SessionManager.list_runs filters by agent correctly."""

    def test_list_runs_by_agent(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        sid = "sess-001"
        mgr.start(sid, user="testuser")
        mgr.create_dispatch("d-001", session_id=sid, user="testuser", prompt="test", dispatch_mode="single", target_agents=["finance", "docs"])
        mgr.create_dispatch("d-002", session_id=sid, user="testuser", prompt="test2", dispatch_mode="single", target_agents=["finance"])
        mgr.start_agent_run("run-001", dispatch_id="d-001", session_id=sid, agent="finance", turn_id="t-1")
        mgr.start_agent_run("run-002", dispatch_id="d-001", session_id=sid, agent="docs", turn_id="t-1")
        mgr.start_agent_run("run-003", dispatch_id="d-002", session_id=sid, agent="finance", turn_id="t-2")

        runs = mgr.list_runs(agent="finance", limit=100)
        assert len(runs) == 2
        assert all(r["agent"] == "finance" for r in runs)

    def test_list_runs_by_agent_returns_empty_for_unknown(self, tmp_path: Path) -> None:
        mgr = SessionManager(db_path=tmp_path / "test.sqlite")
        sid = "sess-001"
        mgr.start(sid, user="testuser")
        mgr.create_dispatch("d-001", session_id=sid, user="testuser", prompt="test", dispatch_mode="single", target_agents=["finance"])
        mgr.start_agent_run("run-001", dispatch_id="d-001", session_id=sid, agent="finance", turn_id="t-1")

        runs = mgr.list_runs(agent="nonexistent", limit=100)
        assert len(runs) == 0
