"""In-memory trace event fan-out for live frontend observability."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TraceEnvelope:
    """User-scoped trace payload for websocket fan-out."""

    user: str
    event: dict[str, Any]


class TraceHub:
    """Simple queue-based pub/sub hub for live trace streaming."""

    def __init__(self, *, queue_size: int = 2000) -> None:
        self._queue_size = max(100, queue_size)
        self._subscribers: set[asyncio.Queue[TraceEnvelope]] = set()

    def subscribe(self) -> asyncio.Queue[TraceEnvelope]:
        queue: asyncio.Queue[TraceEnvelope] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[TraceEnvelope]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, *, user: str, event: dict[str, Any]) -> None:
        envelope = TraceEnvelope(user=user, event=event)
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # Best-effort semantics: drop newest when queue cannot drain.
                continue
