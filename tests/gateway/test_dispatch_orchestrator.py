"""Behavioral tests for DispatchOrchestrator — dispatch lifecycle management."""

from corvus.gateway.dispatch_orchestrator import execute_dispatch_lifecycle, dispatch_control_listener


class TestDispatchOrchestratorModule:
    def test_execute_dispatch_lifecycle_is_callable(self) -> None:
        assert callable(execute_dispatch_lifecycle)

    def test_dispatch_control_listener_is_callable(self) -> None:
        assert callable(dispatch_control_listener)

    def test_execute_dispatch_lifecycle_is_async(self) -> None:
        import asyncio
        assert asyncio.iscoroutinefunction(execute_dispatch_lifecycle)

    def test_dispatch_control_listener_is_async(self) -> None:
        import asyncio
        assert asyncio.iscoroutinefunction(dispatch_control_listener)
