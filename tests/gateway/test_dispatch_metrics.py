"""Behavioral tests for shared dispatch summary aggregation."""

from __future__ import annotations

from corvus.gateway.dispatch_metrics import summarize_dispatch_runs


class TestDispatchMetrics:
    def test_summary_for_successful_dispatch(self) -> None:
        summary = summarize_dispatch_runs(
            [
                {
                    "result": "success",
                    "cost_usd": 0.12,
                    "tokens_used": 1200,
                    "context_pct": 5.2,
                    "context_limit": 200000,
                },
                {
                    "result": "success",
                    "cost_usd": 0.08,
                    "tokens_used": 800,
                    "context_pct": 3.1,
                    "context_limit": 200000,
                },
            ]
        )
        assert summary.total_runs == 2
        assert summary.success_count == 2
        assert summary.error_count == 0
        assert summary.interrupted_count == 0
        assert summary.tokens_used == 2000
        assert summary.cost_usd == 0.2
        assert summary.status == "done"
        assert summary.error is None

    def test_summary_marks_interrupted(self) -> None:
        summary = summarize_dispatch_runs(
            [{"result": "success"}, {"result": "interrupted"}],
            interrupted=True,
        )
        assert summary.total_runs == 2
        assert summary.interrupted_count == 1
        assert summary.status == "interrupted"
        assert summary.error == "interrupted_by_user"

    def test_summary_marks_error(self) -> None:
        summary = summarize_dispatch_runs([{"result": "error"}, {"result": "success"}])
        assert summary.total_runs == 2
        assert summary.success_count == 1
        assert summary.error_count == 1
        assert summary.status == "error"
        assert summary.error == "one_or_more_runs_failed"
