---
subsystem: security/audit
last_verified: 2026-03-09
---

# AuditLog

The `AuditLog` class provides append-only JSONL logging for all tool call invocations. Every tool call -- whether allowed, denied, or failed -- is recorded with timestamp, agent name, session ID, tool name, outcome, optional reason, duration, and a truncated parameter summary. The log file is the authoritative record for session summary building via `SessionLifecycle`.

## Ground Truths

- Storage format is JSONL (one JSON object per line), appended via file open mode `"a"`
- Log directory is created automatically (`mkdir parents=True, exist_ok=True`) on `AuditLog.__init__`
- Each `AuditEntry` contains: `timestamp` (UTC ISO format), `agent_name`, `session_id`, `tool_name`, `outcome`, optional `reason`, optional `duration_ms`, optional `params_summary`
- `outcome` is one of: `"allowed"`, `"denied"`, `"failed"`
- Parameter summaries are truncated: individual values capped at 50 chars, total summary capped at 200 chars
- `read_entries()` supports filtering by `agent_name` and/or `session_id`
- `read_entries()` returns an empty list if the log file does not exist
- Timestamps use `datetime.now(UTC).isoformat()`
- `SessionLifecycle.build_session_summary()` consumes `AuditEntry` lists to produce deterministic `SessionSummary` objects

## Boundaries

- **Depends on:** filesystem (log directory)
- **Consumed by:** `ToolContext` (writes entries), `SessionLifecycle` (reads entries), `corvus/api/` (exposes summaries)
- **Does NOT:** enforce policy, rate limit, or sanitize tool results
