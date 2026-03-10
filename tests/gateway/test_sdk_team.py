"""Team coordination data structure tests."""

from pathlib import Path

from corvus.gateway.sdk_client_manager import TeamContext, TeamMessage, TeamTask


class TestTeamContext:
    def test_create_team_context(self, tmp_path):
        ctx = TeamContext(
            team_name="corvus-team",
            session_id="sess-1",
            members={},
            inbox_dir=tmp_path / "inboxes",
            task_dir=tmp_path / "tasks",
        )
        assert ctx.team_name == "corvus-team"
        assert ctx.members == {}

    def test_team_context_with_members(self, tmp_path):
        from corvus.gateway.sdk_client_manager import ManagedClient
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        ctx = TeamContext(
            team_name="team-1",
            session_id="sess-1",
            members={"work": mc},
            inbox_dir=tmp_path / "inboxes",
            task_dir=tmp_path / "tasks",
        )
        assert "work" in ctx.members
        assert ctx.members["work"].agent_name == "work"


class TestTeamMessage:
    def test_create_message(self):
        msg = TeamMessage(
            from_agent="codex",
            to_agent="work",
            text="Found 3 security issues",
            summary="Security review results",
            timestamp="2026-03-09T12:00:00Z",
            read=False,
            message_type="message",
        )
        assert msg.from_agent == "codex"
        assert msg.message_type == "message"

    def test_broadcast_message(self):
        msg = TeamMessage(
            from_agent="lead",
            to_agent=None,
            text="Starting review phase",
            summary="Phase start",
            timestamp="2026-03-09T12:00:00Z",
            read=False,
            message_type="broadcast",
        )
        assert msg.to_agent is None


class TestTeamTask:
    def test_create_task(self):
        task = TeamTask(
            id="1",
            subject="Review auth module",
            description="Look for SQL injection and XSS",
            status="pending",
            owner=None,
            blocked_by=[],
        )
        assert task.status == "pending"
        assert task.blocked_by == []

    def test_task_with_dependencies(self):
        task = TeamTask(
            id="2",
            subject="Deploy fixes",
            description="Deploy after review",
            status="pending",
            owner="work",
            blocked_by=["1"],
        )
        assert task.blocked_by == ["1"]
