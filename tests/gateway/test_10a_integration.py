"""Integration tests for Slice 10A — verify all new infrastructure works together.

Tests exercise the full pipeline: EventEmitter + hooks + supervisor + ModelRouter.
No mocks — real file I/O, real SQLite, real YAML config.
"""

import asyncio
import json
from pathlib import Path

import pytest

from corvus.capabilities.registry import CapabilitiesRegistry, ModuleHealth, ToolModuleEntry
from corvus.events import EventEmitter, JSONLFileSink
from corvus.hooks import create_hooks
from corvus.model_router import ModelRouter
from corvus.supervisor import AgentSupervisor


class TestFullStackIntegration:
    """All 10A components wired together."""

    def test_event_flows_through_full_pipeline(self, tmp_path: Path):
        """EventEmitter -> JSONLFileSink -> readable JSONL."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))

        # Hook emits tool_call
        hooks = create_hooks(emitter)
        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "test-001",
                None,
            )
        )

        # Supervisor emits heartbeat
        registry = CapabilitiesRegistry()

        def healthy():
            return ModuleHealth(name="test", status="healthy")

        entry = ToolModuleEntry(
            name="test",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=healthy,
        )
        registry.register("test", entry)
        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        asyncio.run(supervisor.heartbeat())

        # Both events in the log
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 2
        events = [json.loads(line) for line in lines]
        types = {e["event_type"] for e in events}
        assert "tool_call" in types
        assert "heartbeat" in types

    def test_model_router_with_real_config(self):
        """ModelRouter loads the actual config/models.yaml."""
        config_path = Path("config/models.yaml")
        if not config_path.exists():
            pytest.skip("config/models.yaml not found")
        router = ModelRouter.from_file(config_path)
        assert router.default_model in {"sonnet", "opus", "haiku"}
        # All agents should resolve to a model
        for agent in ["personal", "work", "homelab", "finance", "email", "docs", "music", "home", "general"]:
            model = router.get_model(agent)
            assert model is not None
            assert len(model) > 0

    def test_model_router_skills_with_real_config(self):
        """ModelRouter loads skills section from actual config."""
        config_path = Path("config/models.yaml")
        if not config_path.exists():
            pytest.skip("config/models.yaml not found")
        router = ModelRouter.from_file(config_path)
        skills = router.list_skills()
        assert len(skills) > 0
        # Skills should resolve models
        for skill in skills:
            model = router.get_skill_model(skill)
            assert model is not None
        # resolve_model with skill should return skill's model
        assert router.resolve_model(agent_name="finance", skill_name="data-transform") == "haiku"

    def test_formerly_gated_tool_passes_through_hooks(self, tmp_path: Path):
        """PreToolUse passes through for formerly confirm-gated tools (gating moved to can_use_tool)."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        hooks = create_hooks(emitter)

        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "mcp__ha__ha_call_service", "tool_input": {}},
                "test-002",
                None,
            )
        )
        # Hook passes through — confirm-gating handled by can_use_tool now
        assert result == {}

        # No confirm_gate event emitted by hooks anymore
        if log.exists():
            log_text = log.read_text().strip()
            if log_text:
                for line in log_text.splitlines():
                    event = json.loads(line)
                    assert event["event_type"] != "confirm_gate"

    def test_hooks_pass_through_env_reads(self, tmp_path: Path):
        """Hooks pass through .env reads — security enforcement is in permissions.deny."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        hooks = create_hooks(emitter)

        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Read", "tool_input": {"file_path": "/app/.env"}},
                "test-003",
                None,
            )
        )
        assert result == {}
        # No security_block event should be emitted
        if log.exists():
            content = log.read_text().strip()
            assert content == "" or "security_block" not in content

    def test_supervisor_heartbeat_with_mixed_health(self, tmp_path: Path):
        """Supervisor correctly reports mixed healthy/unhealthy providers."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        registry = CapabilitiesRegistry()

        def healthy():
            return ModuleHealth(name="email", status="healthy")

        def unhealthy():
            return ModuleHealth(name="obsidian", status="unhealthy")

        email_entry = ToolModuleEntry(
            name="email",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=healthy,
        )
        registry.register("email", email_entry)
        obsidian_entry = ToolModuleEntry(
            name="obsidian",
            configure=lambda cfg: cfg,
            create_tools=lambda cfg: [],
            create_mcp_server=lambda tools, cfg: None,
            health_check=unhealthy,
        )
        registry.register("obsidian", obsidian_entry)

        supervisor = AgentSupervisor(registry=registry, emitter=emitter)
        asyncio.run(supervisor.heartbeat())

        event = json.loads(log.read_text().strip())
        assert event["metadata"]["mcp_servers"]["email"]["status"] == "healthy"
        assert event["metadata"]["mcp_servers"]["obsidian"]["status"] == "unhealthy"
