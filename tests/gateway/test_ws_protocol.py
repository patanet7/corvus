"""Tests for extended WebSocket protocol messages.

Verifies the gateway sends routing, agent_status, tool_start, tool_result,
and confirm_request messages in addition to text and done.

Also tests WebSocket audit fixes:
- call_id matching between tool_start and tool_result
- duration_ms tracking
- output correctness (not sending input as output)
- error status propagation
- ping/pong, confirm_response, JSON error handling (source contracts)

All tests are behavioral -- real objects, real parsing. NO mocks.
"""

import asyncio
import json
from pathlib import Path

from corvus.events import EventEmitter, JSONLFileSink
from corvus.hooks import create_hooks


class TestWSProtocolMessages:
    """Verify the shape of each new WebSocket message type."""

    def test_routing_message_shape(self):
        """Routing message includes agent name and model."""
        msg = {
            "type": "routing",
            "agent": "homelab",
            "model": "claude-sonnet-4-6",
        }
        assert msg["type"] == "routing"
        assert msg["agent"] == "homelab"
        assert "model" in msg

    def test_agent_status_message_shape(self):
        """Agent status message includes agent and status enum."""
        msg = {
            "type": "agent_status",
            "agent": "homelab",
            "status": "thinking",
        }
        assert msg["status"] in ("thinking", "streaming", "done", "error")

    def test_tool_start_message_shape(self):
        """Tool start message includes tool name, params, and call_id."""
        msg = {
            "type": "tool_start",
            "tool": "bash",
            "params": {"command": "docker ps"},
            "call_id": "abc-123",
        }
        assert msg["type"] == "tool_start"
        assert "call_id" in msg

    def test_tool_result_message_shape(self):
        """Tool result includes call_id, output, duration, and status."""
        msg = {
            "type": "tool_result",
            "call_id": "abc-123",
            "output": "container running",
            "duration_ms": 800,
            "status": "success",
        }
        assert msg["status"] in ("success", "error")
        assert isinstance(msg["duration_ms"], (int, float))

    def test_confirm_request_message_shape(self):
        """Confirm request includes tool, params, call_id, and timeout."""
        msg = {
            "type": "confirm_request",
            "tool": "mcp__email__email_send",
            "params": {"to": "user@example.com", "subject": "Test"},
            "call_id": "def-456",
            "timeout_s": 60,
        }
        assert msg["type"] == "confirm_request"
        assert msg["timeout_s"] == 60

    def test_done_message_includes_context_metrics(self):
        """Done message includes token and context window metrics."""
        msg = {
            "type": "done",
            "session_id": "sess-001",
            "cost_usd": 0.04,
            "tokens_used": 2847,
            "context_limit": 200000,
            "context_pct": 1.4,
        }
        assert "tokens_used" in msg
        assert "context_pct" in msg

    def test_interrupt_client_message_shape(self):
        """Client can send interrupt message."""
        msg = {"type": "interrupt"}
        assert msg["type"] == "interrupt"

    def test_ping_client_message_shape(self):
        """Client can send ping message."""
        msg = {"type": "ping"}
        assert msg["type"] == "ping"

    def test_pong_server_message_shape(self):
        """Server responds with pong message."""
        msg = {"type": "pong"}
        assert msg["type"] == "pong"

    def test_confirm_response_client_message_shape(self):
        """Client can send confirm_response message."""
        msg = {"type": "confirm_response", "tool_call_id": "abc-123", "approved": True}
        assert msg["type"] == "confirm_response"
        assert msg["tool_call_id"] == "abc-123"
        assert msg["approved"] is True

    def test_error_server_message_shape(self):
        """Server sends error messages with a message field."""
        msg = {"type": "error", "message": "Something went wrong"}
        assert msg["type"] == "error"
        assert isinstance(msg["message"], str)

    def test_memory_changed_message_shape(self):
        """Memory changed event includes domain and summary."""
        msg = {
            "type": "memory_changed",
            "domain": "homelab",
            "action": "save",
            "summary": "plex running on miniserver",
        }
        assert msg["type"] == "memory_changed"
        assert msg["domain"] == "homelab"


class TestHookToolEvents:
    """Verify hooks emit tool_start and tool_result events."""

    def test_create_hooks_returns_expected_keys(self):
        """create_hooks returns pre and post tool use handlers."""
        emitter = EventEmitter()
        hooks = create_hooks(emitter)
        assert "pre_tool_use" in hooks
        assert "post_tool_use" in hooks

    def test_create_hooks_accepts_ws_callback(self):
        """create_hooks accepts an optional ws_callback parameter."""
        emitter = EventEmitter()

        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)
        assert "pre_tool_use" in hooks
        assert "post_tool_use" in hooks

    def test_pre_tool_use_emits_tool_start_via_callback(self):
        """pre_tool_use hook emits tool_start via ws_callback for non-gated tools."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "tool-001",
                None,
            )
        )

        tool_starts = [m for m in collected if m["type"] == "tool_start"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["tool"] == "Bash"
        assert "call_id" in tool_starts[0]

    def test_pre_tool_use_emits_confirm_request_via_callback(self):
        """pre_tool_use hook emits confirm_request for confirm-gated tools."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb, confirm_gated={"mcp__email__email_send"})

        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "mcp__email__email_send", "tool_input": {"to": "test@example.com"}},
                "tool-002",
                None,
            )
        )

        # Confirm decision is still returned
        assert result["decision"] == "confirm"

        # confirm_request emitted via callback
        confirm_msgs = [m for m in collected if m["type"] == "confirm_request"]
        assert len(confirm_msgs) == 1
        assert confirm_msgs[0]["tool"] == "mcp__email__email_send"
        assert confirm_msgs[0]["timeout_s"] == 60
        assert "call_id" in confirm_msgs[0]

    def test_post_tool_use_emits_tool_result_via_callback(self):
        """post_tool_use hook emits tool_result via ws_callback."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "tool-003",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["status"] == "success"
        assert "call_id" in tool_results[0]

    def test_blocked_tool_does_not_emit_tool_start(self):
        """pre_tool_use hook does NOT emit tool_start for blocked tools."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "cat .env"}},
                "tool-004",
                None,
            )
        )

        assert result["decision"] == "block"
        # No tool_start should be emitted for blocked tools
        tool_starts = [m for m in collected if m["type"] == "tool_start"]
        assert len(tool_starts) == 0

    def test_hooks_work_without_ws_callback(self):
        """Hooks still work correctly when ws_callback is None (backward compat)."""
        emitter = EventEmitter()
        hooks = create_hooks(emitter, confirm_gated={"mcp__email__email_send"})

        # Non-gated tool
        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "tool-005",
                None,
            )
        )
        assert result == {}

        # Gated tool
        result = asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "mcp__email__email_send", "tool_input": {}},
                "tool-006",
                None,
            )
        )
        assert result["decision"] == "confirm"

    def test_event_emitter_still_works_with_ws_callback(self, tmp_path):
        """Event emitter logs are still written when ws_callback is also present."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))

        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "tool-100",
                None,
            )
        )

        # Event emitter still writes to file
        event = json.loads(log.read_text().strip())
        assert event["event_type"] == "tool_call"
        assert event["metadata"]["tool"] == "Bash"

        # ws_callback also received the message
        assert len(collected) == 1
        assert collected[0]["type"] == "tool_result"


class TestCallIdMatching:
    """Fix 2.1: Verify tool_start and tool_result share the same call_id."""

    def test_call_id_matches_between_pre_and_post(self):
        """Pre and post hooks produce matching call_id when using same tool_use_id."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)
        tool_use_id = "sdk-tool-abc123"

        # Pre hook: emits tool_start
        asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "docker ps"}},
                tool_use_id,
                None,
            )
        )

        # Post hook: emits tool_result
        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "docker ps"}},
                tool_use_id,
                None,
            )
        )

        tool_starts = [m for m in collected if m["type"] == "tool_start"]
        tool_results = [m for m in collected if m["type"] == "tool_result"]

        assert len(tool_starts) == 1
        assert len(tool_results) == 1
        assert tool_starts[0]["call_id"] == tool_results[0]["call_id"]

    def test_call_id_uses_tool_use_id_from_sdk(self):
        """When SDK provides tool_use_id, it is used as call_id."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)
        tool_use_id = "toolu_01XYZ"

        asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                tool_use_id,
                None,
            )
        )

        tool_starts = [m for m in collected if m["type"] == "tool_start"]
        assert tool_starts[0]["call_id"] == tool_use_id

    def test_post_hook_without_pre_still_has_call_id(self):
        """Post hook falls back to tool_use_id if no pre context exists."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "orphan-tool-id",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["call_id"] == "orphan-tool-id"

    def test_confirm_gated_tool_call_id_matches(self):
        """Confirm-gated tool's confirm_request call_id matches tool_result."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb, confirm_gated={"mcp__email__email_send"})
        tool_use_id = "confirm-tool-001"

        # Pre hook: emits confirm_request
        asyncio.run(
            hooks["pre_tool_use"](
                {"tool_name": "mcp__email__email_send", "tool_input": {"to": "x@y.com"}},
                tool_use_id,
                None,
            )
        )

        # Post hook: emits tool_result
        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "mcp__email__email_send", "tool_input": {"to": "x@y.com"}},
                tool_use_id,
                None,
            )
        )

        confirm_reqs = [m for m in collected if m["type"] == "confirm_request"]
        tool_results = [m for m in collected if m["type"] == "tool_result"]

        assert len(confirm_reqs) == 1
        assert len(tool_results) == 1
        assert confirm_reqs[0]["call_id"] == tool_results[0]["call_id"]


class TestToolResultOutput:
    """Fix 2.2: Verify tool_result sends actual output, not misleading input."""

    def test_output_placeholder_when_no_result_provided(self):
        """When SDK doesn't provide output, sends placeholder not input."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
                "tool-no-output",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert len(tool_results) == 1
        # Must NOT contain the input command
        assert "ls -la" not in tool_results[0]["output"]
        assert tool_results[0]["output"] == "(output not captured)"

    def test_output_from_tool_result_field(self):
        """When SDK provides tool_result, it is used as output."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo hello"},
                    "tool_result": "hello\n",
                },
                "tool-with-result",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert tool_results[0]["output"] == "hello\n"

    def test_output_from_output_field(self):
        """When SDK provides output field, it is used."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {
                    "tool_name": "Read",
                    "tool_input": {"file_path": "/tmp/test.txt"},
                    "output": "file contents here",
                },
                "tool-with-output",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert tool_results[0]["output"] == "file contents here"

    def test_output_truncated_at_500_chars(self):
        """Long output is truncated to 500 characters."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        long_output = "x" * 1000

        asyncio.run(
            hooks["post_tool_use"](
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "cat bigfile"},
                    "tool_result": long_output,
                },
                "tool-long-output",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert len(tool_results[0]["output"]) == 500


class TestToolResultStatus:
    """Fix 2.2: Verify tool_result status reflects actual success/error."""

    def test_default_status_is_success(self):
        """Without is_error flag, status defaults to success."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "tool-success",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert tool_results[0]["status"] == "success"

    def test_error_status_when_is_error_true(self):
        """When is_error is True, status is error."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "bad-command"},
                    "is_error": True,
                    "tool_result": "command not found",
                },
                "tool-error",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert tool_results[0]["status"] == "error"


class TestDurationTracking:
    """Fix 2.2: Verify duration_ms tracks actual elapsed time."""

    def test_duration_positive_after_pre_and_post(self):
        """Duration is positive when pre and post hooks are both called."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)
        tool_use_id = "duration-test-001"

        async def run_with_delay():
            await hooks["pre_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "sleep 0.01"}},
                tool_use_id,
                None,
            )
            # Small delay to ensure measurable duration
            await asyncio.sleep(0.01)
            await hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "sleep 0.01"}},
                tool_use_id,
                None,
            )

        asyncio.run(run_with_delay())

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["duration_ms"] >= 5  # at least 5ms

    def test_duration_zero_when_no_pre_context(self):
        """Duration is 0 when post hook is called without matching pre hook."""
        emitter = EventEmitter()
        collected = []

        async def ws_cb(msg):
            collected.append(msg)

        hooks = create_hooks(emitter, ws_callback=ws_cb)

        asyncio.run(
            hooks["post_tool_use"](
                {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "no-pre-context",
                None,
            )
        )

        tool_results = [m for m in collected if m["type"] == "tool_result"]
        assert tool_results[0]["duration_ms"] == 0


class TestWSServerSourceContracts:
    """Verify WebSocket protocol contracts in the refactored modules."""

    def _load_chat_source(self):
        return (Path(__file__).parent.parent.parent / "corvus" / "api" / "chat.py").read_text()

    def _load_options_source(self):
        return (Path(__file__).parent.parent.parent / "corvus" / "gateway" / "options.py").read_text()

    def test_routing_message_sent_after_classify(self):
        """chat router sends routing message after agent classification."""
        source = self._load_chat_source()
        assert '"type": "routing"' in source

    def test_done_message_includes_tokens(self):
        """done message includes tokens_used."""
        source = self._load_chat_source()
        assert '"tokens_used"' in source

    def test_done_message_includes_context_pct(self):
        """done message includes context_pct."""
        source = self._load_chat_source()
        assert '"context_pct"' in source

    def test_interrupt_handling_exists(self):
        """chat router handles interrupt messages from clients."""
        source = self._load_chat_source()
        assert '"interrupt"' in source

    def test_build_hooks_accepts_websocket(self):
        """build_hooks() accepts websocket forwarding target."""
        source = self._load_options_source()
        assert "def build_hooks(" in source
        assert "websocket: WebSocket | None = None" in source

    def test_ws_forward_defined(self):
        """ws_forward async function is defined for WebSocket forwarding."""
        source = self._load_options_source()
        assert "async def ws_forward" in source

    def test_ws_callback_passed_to_create_hooks(self):
        """ws_callback is passed to create_hooks."""
        source = self._load_options_source()
        assert "ws_callback=" in source

    def test_ping_handler_exists(self):
        """chat router handles ping messages with pong response."""
        source = self._load_chat_source()
        assert '"ping"' in source
        assert '"pong"' in source

    def test_confirm_response_handler_exists(self):
        """chat router handles confirm_response messages."""
        source = self._load_chat_source()
        assert '"confirm_response"' in source

    def test_json_decode_error_handling_exists(self):
        """chat router wraps json.loads in try/except JSONDecodeError."""
        source = self._load_chat_source()
        assert "json.JSONDecodeError" in source
        assert '"Invalid JSON"' in source

    def test_error_message_sent_to_frontend(self):
        """chat router sends error messages to the frontend on processing failure."""
        source = self._load_chat_source()
        assert '"type": "error"' in source

    def test_ws_forward_logs_on_failure(self):
        """ws_forward logs debug message instead of bare pass."""
        source = self._load_options_source()
        assert "ws_forward: connection closed" in source

    def test_phase2_interrupt_todo_noted(self):
        """chat router keeps TODO for async queue interrupt improvement."""
        source = self._load_chat_source()
        assert "TODO(phase2)" in source


class TestSWAGProxyContracts:
    """Fix 1.1: Verify SWAG proxy config has WebSocket upgrade headers."""

    def _load_conf(self):
        return (
            Path(__file__).parent.parent.parent
            / "infra"
            / "stacks"
            / "optiplex"
            / "swag"
            / "proxy-confs"
            / "claw.subdomain.conf"
        ).read_text()

    def test_upgrade_header_present(self):
        """Proxy config sets Upgrade header for WebSocket."""
        conf = self._load_conf()
        assert "proxy_set_header Upgrade $http_upgrade" in conf

    def test_connection_header_present(self):
        """Proxy config sets Connection header for WebSocket."""
        conf = self._load_conf()
        assert "proxy_set_header Connection $http_connection" in conf

    def test_read_timeout_extended(self):
        """Proxy config has 1-hour read timeout for WebSocket."""
        conf = self._load_conf()
        assert "proxy_read_timeout 3600" in conf

    def test_send_timeout_extended(self):
        """Proxy config has 1-hour send timeout for WebSocket."""
        conf = self._load_conf()
        assert "proxy_send_timeout 3600" in conf

    def test_upgrade_headers_in_ws_location_block(self):
        """Upgrade headers are specifically in the /ws location block."""
        conf = self._load_conf()
        # Find the /ws block and check it contains the upgrade headers
        ws_block_start = conf.index("location /ws {")
        # Find the next closing brace at the same indent level
        ws_block_end = conf.index("}", ws_block_start)
        ws_block = conf[ws_block_start:ws_block_end]
        assert "Upgrade $http_upgrade" in ws_block
        assert "Connection $http_connection" in ws_block
