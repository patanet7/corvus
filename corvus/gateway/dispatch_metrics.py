"""Shared dispatch/run result aggregation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DispatchRunSummary:
    """Aggregated summary for a dispatch across one or more runs."""

    total_runs: int
    success_count: int
    error_count: int
    interrupted_count: int
    tokens_used: int
    cost_usd: float
    max_context_pct: float
    max_context_limit: int
    status: str
    error: str | None


def summarize_dispatch_runs(
    run_results: list[dict[str, Any]],
    *,
    interrupted: bool = False,
) -> DispatchRunSummary:
    """Build aggregate dispatch metrics from route/run result dictionaries."""
    total_runs = len(run_results)
    success_count = sum(1 for result in run_results if result.get("result") == "success")
    interrupted_count = sum(1 for result in run_results if result.get("result") == "interrupted")
    error_count = total_runs - success_count - interrupted_count

    tokens_used = int(sum(int(result.get("tokens_used", 0)) for result in run_results))
    cost_usd = round(sum(float(result.get("cost_usd", 0.0)) for result in run_results), 6)
    max_context_pct = max((float(result.get("context_pct", 0.0)) for result in run_results), default=0.0)
    max_context_limit = max((int(result.get("context_limit", 0)) for result in run_results), default=0)

    if interrupted or interrupted_count > 0:
        status = "interrupted"
        error = "interrupted_by_user"
    elif error_count > 0:
        status = "error"
        error = "one_or_more_runs_failed"
    else:
        status = "done"
        error = None

    return DispatchRunSummary(
        total_runs=total_runs,
        success_count=success_count,
        error_count=error_count,
        interrupted_count=interrupted_count,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
        max_context_pct=max_context_pct,
        max_context_limit=max_context_limit,
        status=status,
        error=error,
    )
