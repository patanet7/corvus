"""Behavioral tests for the sliding-window rate limiter.

Uses small window_seconds (0.1s) for fast expiry tests.
No mocks -- exercises real time.monotonic() timing.
"""

from __future__ import annotations

import time

from corvus.security.rate_limiter import (
    RateLimitConfig,
    SlidingWindowRateLimiter,
)


def _make_limiter(
    mutation_limit: int = 3,
    read_limit: int = 5,
    window_seconds: float = 0.1,
) -> SlidingWindowRateLimiter:
    """Helper to build a limiter with small windows for fast tests."""
    return SlidingWindowRateLimiter(
        config=RateLimitConfig(
            mutation_limit=mutation_limit,
            read_limit=read_limit,
            window_seconds=window_seconds,
        )
    )


def test_first_call_allowed() -> None:
    limiter = _make_limiter()
    result = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert result.allowed is True
    assert result.retry_after_seconds is None


def test_remaining_count_accurate() -> None:
    limiter = _make_limiter(mutation_limit=3)

    # Before any records, remaining should be limit - 0 - 1 = 2
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.remaining == 2

    limiter.record(session_id="s1", tool_name="tool_a")
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.remaining == 1

    limiter.record(session_id="s1", tool_name="tool_a")
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.remaining == 0


def test_exceeding_mutation_limit_denied() -> None:
    limiter = _make_limiter(mutation_limit=3)

    for _ in range(3):
        limiter.record(session_id="s1", tool_name="tool_a")

    result = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert result.allowed is False
    assert result.remaining == 0


def test_exceeding_read_limit_denied() -> None:
    limiter = _make_limiter(read_limit=5)

    for _ in range(5):
        limiter.record(session_id="s1", tool_name="tool_b")

    result = limiter.check(session_id="s1", tool_name="tool_b", is_mutation=False)
    assert result.allowed is False
    assert result.remaining == 0


def test_retry_after_populated_when_denied() -> None:
    limiter = _make_limiter(mutation_limit=2, window_seconds=0.1)

    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_a")

    result = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert result.allowed is False
    assert result.retry_after_seconds is not None
    assert result.retry_after_seconds > 0.0
    assert result.retry_after_seconds <= 0.1


def test_different_tools_have_separate_windows() -> None:
    limiter = _make_limiter(mutation_limit=2)

    # Exhaust tool_a
    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_a")

    # tool_a should be denied
    r_a = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r_a.allowed is False

    # tool_b should still be allowed
    r_b = limiter.check(session_id="s1", tool_name="tool_b", is_mutation=True)
    assert r_b.allowed is True


def test_different_sessions_have_separate_windows() -> None:
    limiter = _make_limiter(mutation_limit=2)

    # Exhaust session s1
    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_a")

    # s1 denied
    r1 = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r1.allowed is False

    # s2 still allowed
    r2 = limiter.check(session_id="s2", tool_name="tool_a", is_mutation=True)
    assert r2.allowed is True


def test_window_expiry_allows_new_calls() -> None:
    limiter = _make_limiter(mutation_limit=2, window_seconds=0.05)

    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_a")

    # Should be denied now
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.allowed is False

    # Wait for window to expire
    time.sleep(0.06)

    # Should be allowed again
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.allowed is True
    assert r.remaining == 1


def test_reset_clears_session_state() -> None:
    limiter = _make_limiter(mutation_limit=2)

    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_b")

    # s1 tool_a is exhausted
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.allowed is False

    # Reset s1
    limiter.reset(session_id="s1")

    # Now s1 should be allowed for both tools
    r_a = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r_a.allowed is True
    r_b = limiter.check(session_id="s1", tool_name="tool_b", is_mutation=True)
    assert r_b.allowed is True


def test_reset_does_not_affect_other_sessions() -> None:
    limiter = _make_limiter(mutation_limit=2)

    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s1", tool_name="tool_a")
    limiter.record(session_id="s2", tool_name="tool_a")
    limiter.record(session_id="s2", tool_name="tool_a")

    limiter.reset(session_id="s1")

    # s1 cleared
    r1 = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r1.allowed is True

    # s2 still exhausted
    r2 = limiter.check(session_id="s2", tool_name="tool_a", is_mutation=True)
    assert r2.allowed is False


def test_mutation_and_read_use_different_limits() -> None:
    limiter = _make_limiter(mutation_limit=2, read_limit=5)

    # Record 3 calls for same tool
    for _ in range(3):
        limiter.record(session_id="s1", tool_name="tool_a")

    # Mutation check should be denied (limit=2, count=3)
    r_mut = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r_mut.allowed is False

    # Read check should still be allowed (limit=5, count=3)
    r_read = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=False)
    assert r_read.allowed is True
    assert r_read.remaining == 1


def test_default_config_values() -> None:
    limiter = SlidingWindowRateLimiter()
    # Should use defaults: 10 mutation, 60 read, 60s window
    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=True)
    assert r.allowed is True
    assert r.remaining == 9  # 10 - 0 - 1

    r = limiter.check(session_id="s1", tool_name="tool_a", is_mutation=False)
    assert r.allowed is True
    assert r.remaining == 59  # 60 - 0 - 1
