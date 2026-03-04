"""LIVE integration tests for the event pipeline.

NO mocks. Real EventEmitter, real JSONLFileSink, real file I/O.
Tests verify events are emitted, written to disk as valid JSONL,
and that the fan-out to multiple sinks works correctly.

Run: uv run pytest tests/integration/test_events_live.py -v
"""

import asyncio
import json
from pathlib import Path

from corvus.events import EventEmitter, JSONLFileSink


def run(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# JSONLFileSink — writes events to real files
# ---------------------------------------------------------------------------


class TestJSONLFileSink:
    """Verify events are written to real files on disk."""

    def test_creates_file_on_first_write(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        sink = JSONLFileSink(log_file)
        run(sink.write({"event_type": "test", "metadata": {}}))
        assert log_file.exists()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        log_file = tmp_path / "deep" / "nested" / "events.jsonl"
        sink = JSONLFileSink(log_file)
        run(sink.write({"event_type": "test", "metadata": {}}))
        assert log_file.exists()

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        sink = JSONLFileSink(log_file)
        event = {"event_type": "heartbeat", "metadata": {"uptime": 42.0}}
        run(sink.write(event))

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event_type"] == "heartbeat"
        assert parsed["metadata"]["uptime"] == 42.0

    def test_appends_multiple_events(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        sink = JSONLFileSink(log_file)

        for i in range(5):
            run(sink.write({"event_type": f"event_{i}", "seq": i}))

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 5
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["event_type"] == f"event_{i}"

    def test_each_line_is_independent_json(self, tmp_path: Path) -> None:
        """Each line must be valid JSON independently (JSONL format)."""
        log_file = tmp_path / "events.jsonl"
        sink = JSONLFileSink(log_file)

        run(sink.write({"event_type": "a"}))
        run(sink.write({"event_type": "b"}))

        for line in log_file.read_text().strip().split("\n"):
            parsed = json.loads(line)  # Should not raise
            assert "event_type" in parsed


# ---------------------------------------------------------------------------
# EventEmitter — central event bus
# ---------------------------------------------------------------------------


class TestEventEmitter:
    """Verify the emitter fans out to sinks and adds metadata."""

    def test_emit_adds_timestamp(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        run(emitter.emit("test_event", key="value"))

        lines = log_file.read_text().strip().split("\n")
        event = json.loads(lines[0])
        assert "timestamp" in event
        assert "T" in event["timestamp"]  # ISO 8601

    def test_emit_preserves_event_type(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        run(emitter.emit("routing_decision", agent="homelab", confidence=0.95))

        event = json.loads(log_file.read_text().strip())
        assert event["event_type"] == "routing_decision"

    def test_emit_preserves_metadata(self, tmp_path: Path) -> None:
        log_file = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        run(emitter.emit("tool_call", tool="mcp__firefly__accounts", agent="finance", duration_ms=120))

        event = json.loads(log_file.read_text().strip())
        assert event["metadata"]["tool"] == "mcp__firefly__accounts"
        assert event["metadata"]["agent"] == "finance"
        assert event["metadata"]["duration_ms"] == 120

    def test_fanout_to_multiple_sinks(self, tmp_path: Path) -> None:
        """Events should be written to ALL registered sinks."""
        file_a = tmp_path / "sink_a.jsonl"
        file_b = tmp_path / "sink_b.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(file_a))
        emitter.register_sink(JSONLFileSink(file_b))

        run(emitter.emit("shared_event", source="test"))

        assert file_a.exists()
        assert file_b.exists()

        event_a = json.loads(file_a.read_text().strip())
        event_b = json.loads(file_b.read_text().strip())
        assert event_a["event_type"] == "shared_event"
        assert event_b["event_type"] == "shared_event"

    def test_emit_no_sinks_no_crash(self) -> None:
        """Emitting with zero sinks registered should not raise."""
        emitter = EventEmitter()
        run(emitter.emit("lonely_event"))  # Should not raise

    def test_bad_sink_doesnt_crash_other_sinks(self, tmp_path: Path) -> None:
        """A failing sink should not prevent other sinks from receiving events."""
        good_file = tmp_path / "good.jsonl"

        class BadSink:
            async def write(self, event):
                raise RuntimeError("Intentional failure")

        emitter = EventEmitter()
        emitter.register_sink(BadSink())
        emitter.register_sink(JSONLFileSink(good_file))

        run(emitter.emit("resilience_test", important="data"))

        # Good sink should still have received the event
        assert good_file.exists()
        event = json.loads(good_file.read_text().strip())
        assert event["event_type"] == "resilience_test"

    def test_event_shape_contract(self, tmp_path: Path) -> None:
        """Every emitted event must have: timestamp, event_type, metadata."""
        log_file = tmp_path / "events.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        run(emitter.emit("contract_check"))

        event = json.loads(log_file.read_text().strip())
        assert set(event.keys()) == {"timestamp", "event_type", "metadata"}

    def test_rapid_emission(self, tmp_path: Path) -> None:
        """Rapidly emitting many events should not lose any."""
        log_file = tmp_path / "rapid.jsonl"
        emitter = EventEmitter()
        emitter.register_sink(JSONLFileSink(log_file))

        async def burst():
            for i in range(50):
                await emitter.emit("burst", seq=i)

        asyncio.run(burst())

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 50
