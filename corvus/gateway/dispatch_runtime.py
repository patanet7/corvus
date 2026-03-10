"""Shared dispatch run execution runtime.

Used by WebSocket and background dispatch flows to execute one or more planned
routes with bounded parallelism and consistent cancellation/error handling.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Any, Protocol

from corvus.gateway.task_planner import TaskRoute


class RunExecutor(Protocol):
    async def __call__(self, route: TaskRoute, *, route_index: int) -> dict[str, Any]: ...


def _interrupted_result() -> dict[str, float | int | str]:
    return {
        "result": "interrupted",
        "cost_usd": 0.0,
        "tokens_used": 0,
        "context_pct": 0.0,
    }


def _error_result() -> dict[str, float | int | str]:
    return {
        "result": "error",
        "cost_usd": 0.0,
        "tokens_used": 0,
        "context_pct": 0.0,
    }


async def execute_dispatch_runs(
    *,
    dispatch_mode: str,
    run_requests: list[TaskRoute],
    max_parallel_agent_runs: int,
    execute_run: RunExecutor,
    logger: structlog.stdlib.BoundLogger,
    dispatch_interrupted: asyncio.Event | None = None,
) -> list[dict[str, Any]]:
    """Execute planned run routes with bounded fan-out.

    Returns per-run result dictionaries. Exceptions from individual run tasks
    are converted into structured `error`/`interrupted` result payloads so the
    caller can aggregate outcomes deterministically.
    """
    interrupt_event = dispatch_interrupted or asyncio.Event()
    run_results: list[dict[str, Any]] = []

    if dispatch_mode == "parallel" and len(run_requests) > 1:
        semaphore = asyncio.Semaphore(max_parallel_agent_runs)

        async def _bounded_execute(route: TaskRoute, route_index: int) -> dict[str, Any]:
            async with semaphore:
                if interrupt_event.is_set():
                    return _interrupted_result()
                return await execute_run(route, route_index=route_index)

        run_tasks = [asyncio.create_task(_bounded_execute(route, index)) for index, route in enumerate(run_requests)]
        pending: set[asyncio.Task[dict[str, Any]]] = set(run_tasks)
        while pending:
            done, pending = await asyncio.wait(
                pending,
                timeout=0.2,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if interrupt_event.is_set():
                for task in pending:
                    task.cancel()
            for task in done:
                try:
                    run_results.append(task.result())
                except asyncio.CancelledError:
                    run_results.append(_interrupted_result())
                except Exception:
                    logger.exception("unexpected_failure_in_parallel_run_task")
                    run_results.append(_error_result())
    else:
        for route_index, route in enumerate(run_requests):
            if interrupt_event.is_set():
                break
            run_task: asyncio.Task[dict[str, Any]] = asyncio.create_task(execute_run(route, route_index=route_index))
            while True:
                done, _pending = await asyncio.wait({run_task}, timeout=0.2)
                if done:
                    try:
                        run_results.append(run_task.result())
                    except asyncio.CancelledError:
                        run_results.append(_interrupted_result())
                    except Exception:
                        logger.exception("unexpected_failure_in_run_task")
                        run_results.append(_error_result())
                    break
                if interrupt_event.is_set():
                    run_task.cancel()

    return run_results
