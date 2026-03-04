"""Tests for gateway security and logging hooks."""

import asyncio
import json
from pathlib import Path

from corvus.events import EventEmitter, JSONLFileSink
from corvus.hooks import check_bash_safety, check_read_safety, create_hooks


def test_blocks_cat_env():
    assert check_bash_safety("cat .env") == "BLOCKED"


def test_blocks_source_env():
    assert check_bash_safety("source ~/.secrets/claw.env") == "BLOCKED"


def test_blocks_head_env():
    assert check_bash_safety("head -5 .env") == "BLOCKED"


def test_blocks_printenv():
    assert check_bash_safety("printenv") == "BLOCKED"


def test_blocks_env_command():
    assert check_bash_safety("env | grep TOKEN") == "BLOCKED"


def test_allows_python_scripts():
    assert check_bash_safety("python /app/scripts/memory_search.py search 'test'") == "ALLOWED"


def test_allows_ssh_commands():
    assert check_bash_safety("ssh user@example-host 'docker ps'") == "ALLOWED"


def test_allows_docker_commands():
    assert check_bash_safety("docker ps --format '{{.Names}}'") == "ALLOWED"


def test_blocks_read_env():
    assert check_read_safety("/home/user/.env") == "BLOCKED"
    assert check_read_safety("/app/.env") == "BLOCKED"
    assert check_read_safety("/Users/foo/.secrets/claw.env") == "BLOCKED"


def test_allows_read_normal():
    assert check_read_safety("/app/scripts/memory_search.py") == "ALLOWED"
    assert check_read_safety("/data/workspace/MEMORY.md") == "ALLOWED"


# --- Confirm-gating tests ---

# Test confirm_gated set for behavioral verification of the hook mechanism.
_TEST_GATED = {"mcp__email__email_send", "mcp__ha__ha_call_service", "mcp__firefly__firefly_create_transaction"}


class TestPreToolUseConfirmGating:
    """Behavioral tests: call the real async hook with explicit confirm_gated set."""

    def _run_hook(self, tool_name: str, tool_input: dict | None = None, gated: set[str] | None = None) -> dict:
        """Run the async hook synchronously for testing."""
        emitter = EventEmitter()
        hooks = create_hooks(emitter, confirm_gated=gated if gated is not None else _TEST_GATED)
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

    def test_empty_gated_set_passes_all(self):
        result = self._run_hook("mcp__email__email_send", gated=set())
        assert result == {}

    def test_bash_env_still_blocked(self):
        """Confirm security blocking still works alongside confirm-gating."""
        result = self._run_hook("Bash", {"command": "cat .env"})
        assert result["decision"] == "block"

    def test_read_env_still_blocked(self):
        """Confirm .env read blocking still works alongside confirm-gating."""
        result = self._run_hook("Read", {"file_path": "/app/.env"})
        assert result["decision"] == "block"

    def test_break_glass_override_allows_secret_commands(self):
        emitter = EventEmitter()
        hooks = create_hooks(emitter, confirm_gated=_TEST_GATED, allow_secret_access=True)
        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "cat .env"}},
                "test-id",
                None,
            )
        )
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
        hooks = create_hooks(emitter, confirm_gated=_TEST_GATED)
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

    def test_pre_tool_use_emits_block_event(self, tmp_path: Path):
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
        assert result["decision"] == "block"
        event = json.loads(log.read_text().strip())
        assert event["event_type"] == "security_block"
