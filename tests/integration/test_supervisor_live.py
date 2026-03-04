"""LIVE integration tests for AgentSupervisor lifecycle.

NO mocks. Real EventEmitter, real CapabilitiesRegistry, real asyncio tasks.
Tests verify the supervisor starts, heartbeats, emits events, and shuts
down gracefully — all with real objects and real concurrency.

Run: uv run pytest tests/integration/test_supervisor_live.py -v
"""

import asyncio
import json
from pathlib import Path

import pytest

from corvus.capabilities.registry import CapabilitiesRegistry, ModuleHealth, ToolModuleEntry
from corvus.events import EventEmitter, JSONLFileSink
from corvus.supervisor import AgentSupervisor


def run(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


def _healthy_provider(name: str) -> ToolModuleEntry:
    """Create a module entry that always reports healthy."""

    def _health() -> ModuleHealth:
        return ModuleHealth(name=name, status="healthy")

    return ToolModuleEntry(
        name=name,
        configure=lambda cfg: cfg,
        create_tools=lambda cfg: [],
        create_mcp_server=lambda tools, cfg: None,
        health_check=_health,
    )


def _unhealthy_provider(name: str) -> ToolModuleEntry:
    """Create a module entry that always reports unhealthy."""

    def _health() -> ModuleHealth:
        return ModuleHealth(name=name, status="unhealthy", detail="connection refused")

    return ToolModuleEntry(
        name=name,
        configure=lambda cfg: cfg,
        create_tools=lambda cfg: [],
        create_mcp_server=lambda tools, cfg: None,
        health_check=_health,
    )


def _failing_health_provider(name: str) -> ToolModuleEntry:
    """Create a module entry whose health check returns unhealthy with error detail."""

    def _health() -> ModuleHealth:
        return ModuleHealth(name=name, status="unhealthy", detail=f"{name} is on fire")

    return ToolModuleEntry(
        name=name,
        configure=lambda cfg: cfg,
        create_tools=lambda cfg: [],
        create_mcp_server=lambda tools, cfg: None,
        health_check=_health,
    )


# ---------------------------------------------------------------------------
# CapabilitiesRegistry
# ---------------------------------------------------------------------------


class TestCapabilitiesRegistry:
    """Verify registry operations with real module entries."""

    def test_register_and_list(self) -> None:
        registry = CapabilitiesRegistry()
        email = _healthy_provider("email")
        firefly = _healthy_provider("firefly")
        registry.register("email", email)
        registry.register("firefly", firefly)
        assert registry.list_available() == ["email", "firefly"]

    def test_duplicate_registration_raises(self) -> None:
        registry = CapabilitiesRegistry()
        entry = _healthy_provider("email")
        registry.register("email", entry)
        with pytest.raises(ValueError, match="already registered"):
            registry.register("email", entry)

    def test_get_registered_module(self) -> None:
        registry = CapabilitiesRegistry()
        entry = _healthy_provider("email")
        registry.register("email", entry)
        result = registry.get_module("email")
        assert result is not None
        assert result.name == "email"

    def test_get_missing_module_returns_none(self) -> None:
        registry = CapabilitiesRegistry()
        assert registry.get_module("nonexistent") is None

    def test_health_all_healthy(self) -> None:
        registry = CapabilitiesRegistry()
        a = _healthy_provider("a")
        b = _healthy_provider("b")
        registry.register("a", a)
        registry.register("b", b)

        results = {name: registry.health(name) for name in registry.list_available()}
        assert len(results) == 2
        assert results["a"].status == "healthy"
        assert results["b"].status == "healthy"

    def test_health_mixed(self) -> None:
        registry = CapabilitiesRegistry()
        good = _healthy_provider("good")
        bad = _unhealthy_provider("bad")
        registry.register("good", good)
        registry.register("bad", bad)

        results = {name: registry.health(name) for name in registry.list_available()}
        assert results["good"].status == "healthy"
        assert results["bad"].status == "unhealthy"
        assert results["bad"].detail == "connection refused"

    def test_unhealthy_with_detail_reported(self) -> None:
        """An unhealthy provider reports its detail message correctly."""
        registry = CapabilitiesRegistry()
        entry = _failing_health_provider("kaboom")
        registry.register("kaboom", entry)

        result = registry.health("kaboom")
        assert result.status == "unhealthy"
        assert "on fire" in result.detail

    def test_empty_registry_health(self) -> None:
        registry = CapabilitiesRegistry()
        results = {name: registry.health(name) for name in registry.list_available()}
        assert results == {}


# ---------------------------------------------------------------------------
# Supervisor — single heartbeat
# ---------------------------------------------------------------------------


class TestSupervisorHeartbeat:
    """Verify a single heartbeat cycle works end-to-end."""

    def test_heartbeat_emits_event(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        entry = _healthy_provider("memory")
        registry.register("memory", entry)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        run(supervisor.heartbeat())

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "heartbeat"

    def test_heartbeat_includes_uptime(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        run(supervisor.heartbeat())

        event = json.loads(log_file.read_text().strip())
        assert "uptime_seconds" in event["metadata"]
        assert event["metadata"]["uptime_seconds"] >= 0

    def test_heartbeat_includes_mcp_status(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        email = _healthy_provider("email")
        firefly = _unhealthy_provider("firefly")
        registry.register("email", email)
        registry.register("firefly", firefly)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        run(supervisor.heartbeat())

        event = json.loads(log_file.read_text().strip())
        mcp = event["metadata"]["mcp_servers"]
        assert mcp["email"]["status"] == "healthy"
        assert mcp["firefly"]["status"] == "unhealthy"

    def test_heartbeat_returns_status_dict(self, tmp_path: Path) -> None:
        registry = CapabilitiesRegistry()
        entry = _healthy_provider("test")
        registry.register("test", entry)
        emitter = EventEmitter()

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        result = run(supervisor.heartbeat())

        assert isinstance(result, dict)
        assert "test" in result
        assert result["test"]["status"] == "healthy"


# ---------------------------------------------------------------------------
# Supervisor — start/stop lifecycle
# ---------------------------------------------------------------------------


class TestSupervisorLifecycle:
    """Verify start() -> heartbeat loop -> graceful_shutdown() works."""

    def test_start_and_stop(self, tmp_path: Path) -> None:
        """Start the supervisor, let it run briefly, then shut it down."""
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        entry = _healthy_provider("memory")
        registry.register("memory", entry)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        async def lifecycle():
            supervisor = AgentSupervisor(
                registry=registry,
                emitter=emitter,
                heartbeat_interval=0.1,  # Fast for testing
            )
            await supervisor.start()
            # Let a few heartbeats happen
            await asyncio.sleep(0.35)
            await supervisor.graceful_shutdown()
            return log_file.read_text().strip().split("\n")

        lines = asyncio.run(lifecycle())
        # Should have at least 2 heartbeats in 0.35s with 0.1s interval
        assert len(lines) >= 2
        for line in lines:
            event = json.loads(line)
            assert event["event_type"] == "heartbeat"

    def test_shutdown_cancels_task(self, tmp_path: Path) -> None:
        """After shutdown, no more heartbeat events should be emitted."""
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        async def lifecycle():
            supervisor = AgentSupervisor(
                registry=registry,
                emitter=emitter,
                heartbeat_interval=0.05,
            )
            await supervisor.start()
            await asyncio.sleep(0.15)
            await supervisor.graceful_shutdown()

            count_at_shutdown = len(log_file.read_text().strip().split("\n"))

            # Wait a bit more — no new events should appear
            await asyncio.sleep(0.2)
            count_after_wait = len(log_file.read_text().strip().split("\n"))

            return count_at_shutdown, count_after_wait

        at_shutdown, after_wait = asyncio.run(lifecycle())
        assert at_shutdown == after_wait, "Events were emitted after shutdown"

    def test_double_shutdown_no_crash(self, tmp_path: Path) -> None:
        """Calling graceful_shutdown() twice should not raise."""
        registry = CapabilitiesRegistry()
        emitter = EventEmitter()

        async def lifecycle():
            supervisor = AgentSupervisor(
                registry=registry,
                emitter=emitter,
                heartbeat_interval=0.1,
            )
            await supervisor.start()
            await asyncio.sleep(0.05)
            await supervisor.graceful_shutdown()
            await supervisor.graceful_shutdown()  # Should not raise

        asyncio.run(lifecycle())

    def test_shutdown_without_start_no_crash(self) -> None:
        """Calling graceful_shutdown() before start() should not raise."""
        registry = CapabilitiesRegistry()
        emitter = EventEmitter()
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        run(supervisor.graceful_shutdown())  # Should not raise


# ---------------------------------------------------------------------------
# Supervisor — degraded fleet
# ---------------------------------------------------------------------------


class TestSupervisorDegradedFleet:
    """Verify supervisor handles unhealthy providers gracefully."""

    def test_heartbeat_with_all_unhealthy(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        broken_a = _unhealthy_provider("broken_a")
        broken_b = _unhealthy_provider("broken_b")
        registry.register("broken_a", broken_a)
        registry.register("broken_b", broken_b)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        result = run(supervisor.heartbeat())

        assert result["broken_a"]["status"] == "unhealthy"
        assert result["broken_b"]["status"] == "unhealthy"

        # Event should still be emitted even when fleet is degraded
        event = json.loads(log_file.read_text().strip())
        assert event["event_type"] == "heartbeat"

    def test_heartbeat_with_failing_health_provider(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        stable = _healthy_provider("stable")
        unstable = _failing_health_provider("unstable")
        registry.register("stable", stable)
        registry.register("unstable", unstable)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        result = run(supervisor.heartbeat())

        assert result["stable"]["status"] == "healthy"
        assert result["unstable"]["status"] == "unhealthy"

    def test_heartbeat_loop_survives_unhealthy(self, tmp_path: Path) -> None:
        """The heartbeat loop should keep running even with unhealthy modules."""
        log_file = tmp_path / "events.jsonl"
        registry = CapabilitiesRegistry()
        entry = _failing_health_provider("flaky")
        registry.register("flaky", entry)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        async def lifecycle():
            supervisor = AgentSupervisor(
                registry=registry,
                emitter=emitter,
                heartbeat_interval=0.1,
            )
            await supervisor.start()
            await asyncio.sleep(0.35)
            await supervisor.graceful_shutdown()
            return log_file.read_text().strip().split("\n")

        lines = asyncio.run(lifecycle())
        # Loop should have continued despite unhealthy modules
        assert len(lines) >= 2
