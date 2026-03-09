---
subsystem: security/rate_limiter
last_verified: 2026-03-09
---

# SlidingWindowRateLimiter

The `SlidingWindowRateLimiter` enforces per-tool, per-session sliding window rate limits to prevent runaway tool execution. It uses separate thresholds for mutation and read operations. The limiter is in-memory and uses `time.monotonic()` for clock-drift-resistant timing.

## Ground Truths

- Default limits: 10 calls/minute for mutations, 60 calls/minute for reads
- Default window size: 60 seconds
- Keyed by `(session_id, tool_name)` tuple
- `check()` does NOT consume a rate limit slot; `record()` must be called separately after successful execution
- `check()` returns a `RateLimitResult` with `allowed` (bool), `remaining` (int), and optional `retry_after_seconds` (float)
- `retry_after_seconds` is computed from the oldest entry in the window (when it will expire)
- Expired timestamps are pruned on every `check()` call
- `reset(session_id)` clears all rate limit state for a session (used on session end)
- `is_mutation` flag on each call determines which limit (mutation vs read) applies

## Boundaries

- **Depends on:** nothing (self-contained, in-memory)
- **Consumed by:** `ToolContext` (checks before execution, records after)
- **Does NOT:** persist rate limit state across restarts, enforce policy rules, or handle authentication
