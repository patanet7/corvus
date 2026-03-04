"""Integration tests for Slice 10B — routing audit and tool pipeline."""

import asyncio
import json
from pathlib import Path

from corvus.events import EventEmitter, JSONLFileSink


class TestRoutingAuditTrail:
    """Verify routing_decision events are emitted."""

    def test_routing_decision_event_structure(self, tmp_path: Path):
        """EventEmitter can emit routing_decision events with correct shape."""
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))

        asyncio.run(
            emitter.emit(
                "routing_decision",
                agent="docs",
                source="webhook",
                webhook_type="paperless",
                query_preview="New document scanned...",
            )
        )

        event = json.loads(log.read_text().strip())
        assert event["event_type"] == "routing_decision"
        assert event["metadata"]["agent"] == "docs"
        assert event["metadata"]["source"] == "webhook"

    def test_routing_decision_has_timestamp(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))

        asyncio.run(emitter.emit("routing_decision", agent="finance", source="webhook"))

        event = json.loads(log.read_text().strip())
        assert "timestamp" in event

    def test_routing_decision_has_webhook_type(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))

        asyncio.run(
            emitter.emit(
                "routing_decision",
                agent="docs",
                source="webhook",
                webhook_type="paperless",
            )
        )

        event = json.loads(log.read_text().strip())
        assert event["metadata"]["webhook_type"] == "paperless"

    def test_routing_decision_has_query_preview(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))

        asyncio.run(
            emitter.emit(
                "routing_decision",
                agent="work",
                source="webhook",
                webhook_type="transcript",
                query_preview="Sprint planning meeting",
            )
        )

        event = json.loads(log.read_text().strip())
        assert event["metadata"]["query_preview"] == "Sprint planning meeting"


class TestToolPipelineIntegration:
    """Verify new tools follow the same patterns as existing tools."""

    def test_all_tool_modules_use_shared_response(self):
        """All tool modules import from the shared response module, not local copies."""
        tools_dir = Path(__file__).parent.parent.parent / "corvus" / "tools"
        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name in ("__init__.py", "response.py"):
                continue
            src = tool_file.read_text()
            assert "from corvus.tools.response import" in src, (
                f"{tool_file.name} does not import from shared claw.tools.response"
            )

    def test_all_tools_use_sanitize(self):
        """All tool modules use sanitize — either directly or via response.py."""
        tools_dir = Path(__file__).parent.parent.parent / "corvus" / "tools"
        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name in ("__init__.py", "response.py"):
                continue
            src = tool_file.read_text()
            has_direct = "from corvus.sanitize import sanitize" in src
            has_via_response = "from corvus.tools.response import" in src
            assert has_direct or has_via_response, (
                f"{tool_file.name} does not use sanitize (directly or via response.py)"
            )

    def test_response_module_uses_sanitize(self):
        """The shared response module must import sanitize directly."""
        tools_dir = Path(__file__).parent.parent.parent / "corvus" / "tools"
        src = (tools_dir / "response.py").read_text()
        assert "from corvus.sanitize import sanitize" in src

    def test_webhooks_has_emit_routing_decision(self):
        """webhooks.py has the _emit_routing_decision helper."""
        src = (Path(__file__).parent.parent.parent / "corvus" / "webhooks.py").read_text()
        assert "def _emit_routing_decision" in src

    def test_webhooks_process_functions_call_emit(self):
        """All process_* functions call _emit_routing_decision."""
        src = (Path(__file__).parent.parent.parent / "corvus" / "webhooks.py").read_text()
        assert src.count("_emit_routing_decision(") >= 5  # definition + 4 calls
