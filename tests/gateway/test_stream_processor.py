"""Behavioral tests for StreamProcessor — no mocks."""

from corvus.gateway.stream_processor import RunContext, RunResult


class TestRunContext:
    def test_create_with_all_fields(self):
        ctx = RunContext(
            dispatch_id="disp-1",
            run_id="run-1",
            task_id="task-run-1",
            session_id="sess-1",
            turn_id="turn-1",
            agent_name="work",
            model_id="claude-sonnet-4-5",
            route_payload={
                "task_type": "direct",
                "subtask_id": None,
                "skill": None,
                "instruction": "do work",
                "route_index": 0,
            },
        )
        assert ctx.agent_name == "work"
        assert ctx.route_payload["task_type"] == "direct"


class TestRunResult:
    def test_success_result(self):
        result = RunResult(
            status="success",
            tokens_used=1500,
            cost_usd=0.05,
            context_pct=12.5,
            response_text="Hello world",
            sdk_session_id="sdk-abc",
            checkpoints=["msg-1"],
        )
        assert result.status == "success"
        assert result.tokens_used == 1500

    def test_error_result(self):
        result = RunResult(
            status="error",
            tokens_used=0,
            cost_usd=0.0,
            context_pct=0.0,
            response_text="",
            sdk_session_id=None,
            checkpoints=[],
        )
        assert result.status == "error"
