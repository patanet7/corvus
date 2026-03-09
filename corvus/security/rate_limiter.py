"""Sliding-window rate limiter for tool calls.

Prevents runaway tool execution (e.g., mass-deleting HA entities).
Default limits: 10/min for mutations, 60/min for reads.
Per-agent overrides via agent YAML config.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting thresholds."""

    mutation_limit: int = 10  # per window
    read_limit: int = 60  # per window
    window_seconds: float = 60.0


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    retry_after_seconds: float | None = None


class SlidingWindowRateLimiter:
    """Per-tool, per-session sliding window rate limiter."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        # Key: (session_id, tool_name) -> list of timestamps
        self._windows: dict[tuple[str, str], list[float]] = defaultdict(list)

    def check(
        self,
        *,
        session_id: str,
        tool_name: str,
        is_mutation: bool,
    ) -> RateLimitResult:
        """Check if a tool call is within rate limits.

        Does NOT consume a slot -- call record() after successful execution.
        """
        key = (session_id, tool_name)
        limit = self._config.mutation_limit if is_mutation else self._config.read_limit
        now = time.monotonic()
        window_start = now - self._config.window_seconds

        # Prune expired entries
        self._windows[key] = [t for t in self._windows[key] if t > window_start]

        count = len(self._windows[key])
        if count >= limit:
            # Calculate retry_after from oldest entry in window
            oldest = self._windows[key][0]
            retry_after = oldest + self._config.window_seconds - now
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after_seconds=max(0.0, retry_after),
            )

        return RateLimitResult(
            allowed=True,
            remaining=limit - count - 1,
        )

    def record(self, *, session_id: str, tool_name: str) -> None:
        """Record a tool call timestamp."""
        key = (session_id, tool_name)
        self._windows[key].append(time.monotonic())

    def reset(self, *, session_id: str) -> None:
        """Clear all rate limit state for a session (e.g., on session end)."""
        keys_to_remove = [k for k in self._windows if k[0] == session_id]
        for k in keys_to_remove:
            del self._windows[k]
