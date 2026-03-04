"""Behavioral tests for shared dispatch runtime executor."""

from __future__ import annotations

import asyncio
import logging

from corvus.gateway.dispatch_runtime import execute_dispatch_runs
from corvus.gateway.task_planner import TaskRoute


class TestDispatchRuntime:
    def test_parallel_mode_executes_all_routes(self) -> None:
        routes = [
            TaskRoute(agent="a", prompt="p1", requested_model=None),
            TaskRoute(agent="b", prompt="p2", requested_model=None),
            TaskRoute(agent="c", prompt="p3", requested_model=None),
        ]

        async def _run() -> list[dict]:
            async def executor(route: TaskRoute, *, route_index: int) -> dict:
                await asyncio.sleep(0.01 if route_index % 2 == 0 else 0.02)
                return {"result": "success", "agent": route.agent, "idx": route_index}

            return await execute_dispatch_runs(
                dispatch_mode="parallel",
                run_requests=routes,
                max_parallel_agent_runs=2,
                execute_run=executor,
                logger=logging.getLogger("test-dispatch-runtime"),
            )

        results = asyncio.run(_run())
        assert len(results) == 3
        assert sum(1 for result in results if result["result"] == "success") == 3

    def test_sequential_mode_stops_after_interrupt(self) -> None:
        routes = [
            TaskRoute(agent="a", prompt="p1", requested_model=None),
            TaskRoute(agent="b", prompt="p2", requested_model=None),
        ]
        interrupt_event = asyncio.Event()
        seen_indices: list[int] = []

        async def _run() -> list[dict]:
            async def executor(_route: TaskRoute, *, route_index: int) -> dict:
                seen_indices.append(route_index)
                if route_index == 0:
                    interrupt_event.set()
                return {"result": "success", "idx": route_index}

            return await execute_dispatch_runs(
                dispatch_mode="direct",
                run_requests=routes,
                max_parallel_agent_runs=2,
                execute_run=executor,
                logger=logging.getLogger("test-dispatch-runtime"),
                dispatch_interrupted=interrupt_event,
            )

        results = asyncio.run(_run())
        assert seen_indices == [0]
        assert len(results) == 1
        assert results[0]["result"] == "success"

    def test_run_exceptions_convert_to_error_result(self) -> None:
        routes = [
            TaskRoute(agent="a", prompt="p1", requested_model=None),
            TaskRoute(agent="b", prompt="p2", requested_model=None),
        ]

        async def _run() -> list[dict]:
            async def executor(_route: TaskRoute, *, route_index: int) -> dict:
                if route_index == 1:
                    raise RuntimeError("boom")
                return {"result": "success", "idx": route_index}

            return await execute_dispatch_runs(
                dispatch_mode="parallel",
                run_requests=routes,
                max_parallel_agent_runs=2,
                execute_run=executor,
                logger=logging.getLogger("test-dispatch-runtime"),
            )

        results = asyncio.run(_run())
        assert len(results) == 2
        assert sum(1 for result in results if result["result"] == "error") == 1
        assert sum(1 for result in results if result["result"] == "success") == 1
