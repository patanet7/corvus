"""Behavioral tests for RunExecutor — the extracted execute_agent_run.

Verifies that the RunExecutor function exists and has the expected signature.
Full integration testing requires SDK + model, so we test the module structure
and the helper extraction only.
"""

from corvus.gateway.run_executor import execute_agent_run


class TestRunExecutorModule:
    """Verify the extracted module exists and has correct exports."""

    def test_execute_agent_run_is_callable(self) -> None:
        assert callable(execute_agent_run)

    def test_execute_agent_run_is_async(self) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(execute_agent_run)


class TestRunExecutorHelpers:
    """Verify module-level helpers are correct."""

    def test_preview_summary_short_text(self) -> None:
        from corvus.gateway.run_executor import _preview_summary

        assert _preview_summary("hello world") == "hello world"

    def test_preview_summary_collapses_whitespace(self) -> None:
        from corvus.gateway.run_executor import _preview_summary

        assert _preview_summary("hello   world\n\tfoo") == "hello world foo"

    def test_preview_summary_truncates_long_text(self) -> None:
        from corvus.gateway.run_executor import _preview_summary

        long_text = "a" * 200
        result = _preview_summary(long_text, limit=160)
        assert len(result) == 160
        assert result.endswith("\u2026")

    def test_preview_summary_exact_limit_no_truncation(self) -> None:
        from corvus.gateway.run_executor import _preview_summary

        text = "a" * 160
        assert _preview_summary(text, limit=160) == text

    def test_route_payload_structure(self) -> None:
        from corvus.gateway.run_executor import _route_payload
        from corvus.gateway.task_planner import TaskRoute

        route = TaskRoute(
            agent="work",
            prompt="do something",
            task_type="single",
            subtask_id=None,
            skill=None,
            instruction=None,
            requested_model=None,
        )
        payload = _route_payload(route, route_index=0)
        assert payload == {
            "task_type": "single",
            "subtask_id": None,
            "skill": None,
            "instruction": None,
            "route_index": 0,
        }

    def test_route_payload_with_subtask(self) -> None:
        from corvus.gateway.run_executor import _route_payload
        from corvus.gateway.task_planner import TaskRoute

        route = TaskRoute(
            agent="finance",
            prompt="check budget",
            task_type="decomposed",
            subtask_id="sub-1",
            skill="budget_check",
            instruction="Review monthly budget",
            requested_model=None,
        )
        payload = _route_payload(route, route_index=2)
        assert payload == {
            "task_type": "decomposed",
            "subtask_id": "sub-1",
            "skill": "budget_check",
            "instruction": "Review monthly budget",
            "route_index": 2,
        }
