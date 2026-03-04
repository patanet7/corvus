"""Behavioral tests for the EventEmitter and sinks."""

import asyncio
import json
from pathlib import Path

from corvus.events import EventEmitter, JSONLFileSink


class TestJSONLFileSink:
    """JSONLFileSink writes events as newline-delimited JSON."""

    def test_write_single_event(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        sink = JSONLFileSink(log)
        asyncio.run(sink.write({"event_type": "test", "metadata": {"key": "val"}}))
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event_type"] == "test"
        assert "metadata" in parsed

    def test_write_multiple_events_appends(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        sink = JSONLFileSink(log)
        asyncio.run(sink.write({"event_type": "a"}))
        asyncio.run(sink.write({"event_type": "b"}))
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_creates_parent_dirs(self, tmp_path: Path):
        log = tmp_path / "deep" / "nested" / "events.jsonl"
        sink = JSONLFileSink(log)
        asyncio.run(sink.write({"event_type": "test"}))
        assert log.exists()


class TestEventEmitter:
    """EventEmitter fans out to all registered sinks."""

    def test_emit_writes_to_all_sinks(self, tmp_path: Path):
        log1 = tmp_path / "a.jsonl"
        log2 = tmp_path / "b.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log1))
        emitter.register_sink(JSONLFileSink(log2))
        asyncio.run(emitter.emit("tool_call", tool="Bash", agent="homelab"))
        assert log1.exists()
        assert log2.exists()
        parsed = json.loads(log1.read_text().strip())
        assert parsed["event_type"] == "tool_call"
        assert parsed["metadata"]["tool"] == "Bash"
        assert parsed["metadata"]["agent"] == "homelab"

    def test_emit_includes_timestamp(self, tmp_path: Path):
        log = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log))
        asyncio.run(emitter.emit("heartbeat", uptime=100))
        parsed = json.loads(log.read_text().strip())
        assert "timestamp" in parsed
        assert "T" in parsed["timestamp"]

    def test_emit_no_sinks_does_not_raise(self):
        emitter = EventEmitter()
        asyncio.run(emitter.emit("test"))  # Should not raise

    def test_sink_error_does_not_propagate(self, tmp_path: Path):
        """A failing sink should not crash the emitter."""
        log = tmp_path / "good.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(Path("/nonexistent/readonly/bad.jsonl")))
        emitter.register_sink(JSONLFileSink(log))
        asyncio.run(emitter.emit("test"))
        assert log.exists()
