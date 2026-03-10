"""Tests for gateway event-emitting hooks."""

import asyncio
import json
from pathlib import Path

from corvus.events import EventEmitter, JSONLFileSink
from corvus.hooks import create_hooks


# --- Confirm-gating tests ---

# Test confirm_gated set for behavioral verification of the hook mechanism.
_TEST_GATED = {"mcp__email__email_send", "mcp__ha__ha_call_service", "mcp__firefly__firefly_create_transaction"}


class TestPreToolUsePassthrough:
    """Behavioral tests: hooks pass all tool calls through (security is handled by permissions.deny)."""

    def _run_hook(self, tool_name: str, tool_input: dict | None = None) -> dict:
        """Run the async hook synchronously for testing."""
        emitter = EventEmitter()
        hooks = create_hooks(emitter)
        input_data = {"tool_name": tool_name, "tool_input": tool_input or {}}
        return asyncio.run(hooks["pre_tool_use"](input_data, "test-id", None))

    def test_formerly_gated_tool_passes_through(self):
        """Confirm-gating moved to can_use_tool callback; hooks pass through."""
        result = self._run_hook("mcp__email__email_send")
        assert result == {}

    def test_ha_call_service_passes_through(self):
        """Confirm-gating moved to can_use_tool callback; hooks pass through."""
        result = self._run_hook("mcp__ha__ha_call_service")
        assert result == {}

    def test_firefly_passes_through(self):
        """Confirm-gating moved to can_use_tool callback; hooks pass through."""
        result = self._run_hook("mcp__firefly__firefly_create_transaction")
        assert result == {}

    def test_non_gated_tool_passes_through(self):
        result = self._run_hook("mcp__email__email_list")
        assert result == {}

    def test_bash_commands_pass_through(self):
        """Security enforcement is now handled by permissions.deny, not hooks."""
        result = self._run_hook("Bash", {"command": "cat .env"})
        assert result == {}

    def test_read_env_passes_through(self):
        """Security enforcement is now handled by permissions.deny, not hooks."""
        result = self._run_hook("Read", {"file_path": "/app/.env"})
        assert result == {}


# --- EventEmitter-based hooks tests ---


class TestEventEmittingHooks:
    """Hooks emit events via EventEmitter instead of direct file writes."""

    def test_post_tool_use_emits_tool_call_event(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        hooks = create_hooks(emitter)
        post_hook = hooks["post_tool_use"]
        asyncio.run(
            post_hook(
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "tool-123",
                None,
            )
        )
        event = json.loads(log.read_text().strip())
        assert event["event_type"] == "tool_call"
        assert event["metadata"]["tool"] == "Bash"

    def test_pre_tool_use_does_not_emit_confirm_gate_event(self, tmp_path: Path):
        """Confirm-gating moved to can_use_tool; hooks must NOT emit confirm_gate."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        hooks = create_hooks(emitter)
        pre_hook = hooks["pre_tool_use"]
        result = asyncio.run(
            pre_hook(
                {"tool_name": "mcp__email__email_send", "tool_input": {}},
                "tool-456",
                None,
            )
        )
        assert result == {}
        # No confirm_gate event should be written
        if log.exists():
            content = log.read_text().strip()
            assert content == "" or "confirm_gate" not in content

    def test_pre_tool_use_no_block_events(self, tmp_path: Path):
        """Hooks no longer emit security_block events — permissions.deny handles blocking."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        hooks = create_hooks(emitter)
        pre_hook = hooks["pre_tool_use"]
        result = asyncio.run(
            pre_hook(
                {"tool_name": "Bash", "tool_input": {"command": "cat .env"}},
                "tool-789",
                None,
            )
        )
        assert result == {}
        if log.exists():
            content = log.read_text().strip()
            assert content == "" or "security_block" not in content
