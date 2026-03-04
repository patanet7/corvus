"""Behavioral tests for the AgentSupervisor lifecycle manager."""

import asyncio
import json
from pathlib import Path

import pytest

from corvus.capabilities.registry import CapabilitiesRegistry, ModuleHealth, ToolModuleEntry
from corvus.events import EventEmitter, JSONLFileSink
from corvus.supervisor import MAX_RESTART_ATTEMPTS, AgentSupervisor


def _make_healthy_provider(name: str) -> ToolModuleEntry:
    def check():
        return ModuleHealth(name=name, status="healthy")

    return ToolModuleEntry(
        name=name,
        configure=lambda cfg: cfg,
        create_tools=lambda cfg: [],
        create_mcp_server=lambda tools, cfg: None,
        health_check=check,
    )


def _make_failing_provider(name: str, fail_count: int = 1) -> ToolModuleEntry:
    """Provider that fails health check `fail_count` times, then succeeds."""
    state = {"failures": 0}

    def check():
        if state["failures"] < fail_count:
            state["failures"] += 1
            return ModuleHealth(name=name, status="unhealthy")
        return ModuleHealth(name=name, status="healthy")

    return ToolModuleEntry(
        name=name,
        configure=lambda cfg: cfg,
        create_tools=lambda cfg: [],
        create_mcp_server=lambda tools, cfg: None,
        health_check=check,
    )


class TestAgentSupervisor:
    def test_heartbeat_emits_event(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        registry = CapabilitiesRegistry()
        entry = _make_healthy_provider("email")
        registry.register(entry.name, entry)
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        asyncio.run(supervisor.heartbeat())
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "heartbeat"
        assert "email" in event["metadata"]["mcp_servers"]
        assert event["metadata"]["mcp_servers"]["email"]["status"] == "healthy"

    def test_heartbeat_reports_unhealthy_provider(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        registry = CapabilitiesRegistry()
        entry = _make_failing_provider("obsidian", fail_count=99)
        registry.register(entry.name, entry)
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        asyncio.run(supervisor.heartbeat())
        event = json.loads(log.read_text().strip())
        assert event["metadata"]["mcp_servers"]["obsidian"]["status"] == "unhealthy"

    def test_heartbeat_includes_uptime(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        registry = CapabilitiesRegistry()
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        asyncio.run(supervisor.heartbeat())
        event = json.loads(log.read_text().strip())
        assert "uptime_seconds" in event["metadata"]

    def test_heartbeat_with_no_providers(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        registry = CapabilitiesRegistry()
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        asyncio.run(supervisor.heartbeat())
        event = json.loads(log.read_text().strip())
        assert event["metadata"]["mcp_servers"] == {}


class TestSupervisorRestart:
    """Verify supervisor auto-restarts unhealthy providers."""

    def test_unhealthy_provider_gets_restarted(self, tmp_path: Path):
        """Supervisor calls restart on unhealthy providers."""
        restart_count = 0

        def health():
            nonlocal restart_count
            if restart_count == 0:
                return ModuleHealth(
                    name="flaky",
                    status="unhealthy",
                )
            return ModuleHealth(
                name="flaky",
                status="healthy",
            )

        async def restart():
            nonlocal restart_count
            restart_count += 1

        entry = ToolModuleEntry(
            name="flaky",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        asyncio.run(supervisor.heartbeat())
        assert restart_count == 1

    def test_healthy_provider_not_restarted(self, tmp_path: Path):
        """Supervisor does NOT restart healthy providers."""
        restart_count = 0

        def health():
            return ModuleHealth(
                name="stable",
                status="healthy",
            )

        async def restart():
            nonlocal restart_count
            restart_count += 1

        entry = ToolModuleEntry(
            name="stable",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        asyncio.run(supervisor.heartbeat())
        assert restart_count == 0

    def test_provider_without_restart_callable_skipped(self, tmp_path: Path):
        """Unhealthy provider without restart callable is reported but not restarted."""

        def health():
            return ModuleHealth(
                name="no-restart",
                status="unhealthy",
            )

        entry = ToolModuleEntry(
            name="no-restart",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            # restart is None (default)
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        # Should not crash
        result = asyncio.run(supervisor.heartbeat())
        assert result["no-restart"]["status"] == "unhealthy"

    def test_restart_event_emitted(self, tmp_path: Path):
        """Supervisor emits provider_restart event when restarting."""

        def health():
            return ModuleHealth(
                name="flaky",
                status="unhealthy",
            )

        async def restart():
            pass

        entry = ToolModuleEntry(
            name="flaky",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        events_file = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(events_file))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        asyncio.run(supervisor.heartbeat())

        events = [json.loads(line) for line in events_file.read_text().splitlines()]
        restart_events = [e for e in events if e.get("event_type") == "provider_restart"]
        assert len(restart_events) >= 1
        assert restart_events[0]["metadata"]["provider"] == "flaky"

    def test_restart_failure_does_not_crash_heartbeat(self, tmp_path: Path):
        """If restart() raises, heartbeat still completes and emits events."""

        def health():
            return ModuleHealth(
                name="crashy",
                status="unhealthy",
            )

        async def restart():
            raise RuntimeError("restart exploded")

        entry = ToolModuleEntry(
            name="crashy",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        events_file = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(events_file))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        # Should NOT raise — heartbeat must be resilient
        result = asyncio.run(supervisor.heartbeat())
        assert result["crashy"]["status"] == "unhealthy"

        # Heartbeat event should still be emitted
        events = [json.loads(line) for line in events_file.read_text().splitlines()]
        heartbeat_events = [e for e in events if e.get("event_type") == "heartbeat"]
        assert len(heartbeat_events) == 1

    def test_multiple_providers_mixed_health(self, tmp_path: Path):
        """Only unhealthy providers with restart callable get restarted."""
        restarted_names: list[str] = []

        def healthy_check():
            return ModuleHealth(
                name="good",
                status="healthy",
            )

        def unhealthy_check():
            return ModuleHealth(
                name="bad",
                status="unhealthy",
            )

        def unhealthy_no_restart_check():
            return ModuleHealth(
                name="bad-no-restart",
                status="unhealthy",
            )

        async def restart_bad():
            restarted_names.append("bad")

        async def restart_good():
            restarted_names.append("good")

        registry = CapabilitiesRegistry()
        good_entry = ToolModuleEntry(
            name="good",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=healthy_check,
            restart=restart_good,
        )
        registry.register(good_entry.name, good_entry)
        bad_entry = ToolModuleEntry(
            name="bad",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=unhealthy_check,
            restart=restart_bad,
        )
        registry.register(bad_entry.name, bad_entry)
        no_restart_entry = ToolModuleEntry(
            name="bad-no-restart",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=unhealthy_no_restart_check,
            # No restart callable
        )
        registry.register(no_restart_entry.name, no_restart_entry)

        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        asyncio.run(supervisor.heartbeat())

        # Only "bad" should have been restarted (unhealthy + has restart callable)
        assert restarted_names == ["bad"]


class TestRestartRetryCap:
    """Verify restart attempts are capped at MAX_RESTART_ATTEMPTS."""

    def test_restart_stops_after_max_attempts(self, tmp_path: Path):
        """Provider is not restarted beyond MAX_RESTART_ATTEMPTS."""
        restart_count = 0

        def health():
            return ModuleHealth(name="broken", status="unhealthy")

        async def restart():
            nonlocal restart_count
            restart_count += 1

        entry = ToolModuleEntry(
            name="broken",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        # Run many heartbeat cycles
        for _ in range(MAX_RESTART_ATTEMPTS + 5):
            asyncio.run(supervisor.heartbeat())

        # Should be capped at exactly MAX_RESTART_ATTEMPTS
        assert restart_count == MAX_RESTART_ATTEMPTS

    def test_restart_counter_resets_on_recovery(self, tmp_path: Path):
        """If provider recovers, restart counter resets — can restart again later."""
        restart_count = 0
        health_cycle = 0

        def health():
            nonlocal health_cycle
            health_cycle += 1
            # Unhealthy for cycles 1-3, healthy for 4-5, unhealthy again for 6+
            if health_cycle <= 3:
                return ModuleHealth(name="flaky", status="unhealthy")
            if health_cycle <= 5:
                return ModuleHealth(name="flaky", status="healthy")
            return ModuleHealth(name="flaky", status="unhealthy")

        async def restart():
            nonlocal restart_count
            restart_count += 1

        entry = ToolModuleEntry(
            name="flaky",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        # Run 8 cycles: 3 unhealthy (3 restarts), 2 healthy (reset), 3 unhealthy (3 more)
        for _ in range(8):
            asyncio.run(supervisor.heartbeat())

        # Counter reset after recovery, so total restarts = 3 + 3 = 6
        assert restart_count == 6

    def test_mcp_status_reflects_restart_in_same_cycle(self, tmp_path: Path):
        """The heartbeat mcp_status reflects the restart in the same cycle."""

        def health():
            return ModuleHealth(name="flaky", status="unhealthy")

        async def restart():
            pass

        entry = ToolModuleEntry(
            name="flaky",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        result = asyncio.run(supervisor.heartbeat())
        # After restart, status is updated to "restarting" in the same cycle
        assert result["flaky"]["status"] == "restarting"


class TestRestartProvider:
    """Verify the restart_provider() public API."""

    def test_restart_provider_calls_restart(self, tmp_path: Path):
        """Manual restart_provider() invokes the restart callable."""
        restarted = False

        def health():
            return ModuleHealth(name="svc", status="healthy")

        async def restart():
            nonlocal restarted
            restarted = True

        entry = ToolModuleEntry(
            name="svc",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        asyncio.run(supervisor.restart_provider("svc"))
        assert restarted is True

    def test_restart_provider_resets_counter(self, tmp_path: Path):
        """Manual restart_provider() resets the retry counter."""
        restart_count = 0

        def health():
            return ModuleHealth(name="svc", status="unhealthy")

        async def restart():
            nonlocal restart_count
            restart_count += 1

        entry = ToolModuleEntry(
            name="svc",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=health,
            restart=restart,
        )
        registry = CapabilitiesRegistry()
        registry.register(entry.name, entry)
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        # Exhaust auto-restart attempts
        for _ in range(MAX_RESTART_ATTEMPTS + 2):
            asyncio.run(supervisor.heartbeat())
        assert restart_count == MAX_RESTART_ATTEMPTS

        # Manual restart resets counter
        asyncio.run(supervisor.restart_provider("svc"))
        assert restart_count == MAX_RESTART_ATTEMPTS + 1

        # Now auto-restart works again
        asyncio.run(supervisor.heartbeat())
        assert restart_count == MAX_RESTART_ATTEMPTS + 2

    def test_restart_provider_unknown_raises(self, tmp_path: Path):
        """restart_provider() raises KeyError for unknown providers."""
        registry = CapabilitiesRegistry()
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(tmp_path / "events.jsonl"))
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)

        with pytest.raises(KeyError):
            asyncio.run(supervisor.restart_provider("nonexistent"))
