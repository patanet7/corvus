"""Extensible event system — central EventEmitter with pluggable sinks.

All gateway events (tool calls, heartbeats, sessions, routing decisions,
confirm-gates) flow through the EventEmitter. Sinks consume events —
currently JSONL files, future: direct Loki push, stdout, webhooks.

Adding a new event type: just call emitter.emit("new_type", **metadata).
Adding a new sink: implement EventSink protocol, call emitter.register_sink().
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypedDict

import structlog


class SecurityBlockEvent(TypedDict):
    """Metadata for security_block events."""

    tool: str
    reason: str
    tool_use_id: str


class RoutingDecisionEvent(TypedDict):
    """Metadata for routing_decision events."""

    agent: str
    backend: str
    source: str
    query_preview: str


class SessionEvent(TypedDict, total=False):
    """Metadata for session_start/session_end events."""

    user: str
    session_id: str
    message_count: int
    duration_seconds: float


logger = structlog.get_logger(__name__)


class EventSink(Protocol):
    """Protocol for event consumers."""

    async def write(self, event: dict[str, Any]) -> None: ...


class JSONLFileSink:
    """Writes events as newline-delimited JSON to a file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def write(self, event: dict[str, Any]) -> None:
        def _write() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(json.dumps(event) + "\n")

        await asyncio.to_thread(_write)


class EventEmitter:
    """Central event bus. Fans out events to all registered sinks."""

    # After this many consecutive failures, log at ERROR instead of WARNING.
    _ERROR_THRESHOLD = 5

    def __init__(self) -> None:
        self.sinks: list[EventSink] = []
        self._sink_failures: dict[int, int] = {}  # id(sink) -> consecutive failures

    def register_sink(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    async def emit(self, event_type: str, **metadata: Any) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "metadata": metadata,
        }
        for sink in self.sinks:
            try:
                await sink.write(event)
                self._sink_failures.pop(id(sink), None)
            except Exception:
                count = self._sink_failures.get(id(sink), 0) + 1
                self._sink_failures[id(sink)] = count
                log_fn = logger.error if count >= self._ERROR_THRESHOLD else logger.warning
                log_fn(
                    "event_sink_failed",
                    sink=type(sink).__name__,
                    event_type=event_type,
                    consecutive_failures=count,
                    exc_info=True,
                )
