# structlog Migration Design

**Date:** 2026-03-10
**Status:** Approved
**Goal:** Replace stdlib `logging` with `structlog` across all 57 modules for structured JSON output (aggregation-ready) and pretty colored console output (dev/troubleshooting).

## Architecture

### Central Config Module: `corvus/logging.py`

Single module that:
- Configures structlog processor pipeline, renderer selection
- Reads env-based log levels (global + per-component)
- Exports `configure_logging()` called once at each entry point

### Renderer Selection

`LOG_FORMAT` env var (default: `console`):
- `console` → structlog `ConsoleRenderer` (colored key=value pairs)
- `json` → structlog `JSONRenderer` (machine-parseable for Loki/Datadog)

### Per-Component Log Levels

Global default via `LOG_LEVEL` (default: `INFO`). Per-component overrides:

| Env Var | Modules Covered |
|---|---|
| `LOG_LEVEL` | Global default |
| `LOG_LEVEL_ROUTER` | `corvus.router` |
| `LOG_LEVEL_STREAM` | `corvus.gateway.stream_processor` |
| `LOG_LEVEL_GATEWAY` | `corvus.gateway.*` (catch-all) |
| `LOG_LEVEL_TUI` | `corvus.tui.*` |
| `LOG_LEVEL_CLI` | `corvus.cli.*` |
| `LOG_LEVEL_MEMORY` | `corvus.memory.*` |
| `LOG_LEVEL_SECURITY` | `corvus.security.*` |
| `LOG_LEVEL_ACP` | `corvus.acp.*` |

Implemented as a custom structlog processor that checks the logger name prefix against the component map and drops events below the configured level.

### Processor Pipeline

```
1. contextvars merge       — auto-include session_id, user, agent, dispatch_id, turn_id
2. add log level           — structlog stdlib
3. add timestamp           — ISO 8601
4. add logger name         — module path (__name__)
5. per-component filter    — drop events below component's configured level
6. scrub secrets/PII       — reuse SANITIZER_PATTERNS from corvus/security/sanitizer.py
7. renderer                — ConsoleRenderer (dev) or JSONRenderer (prod)
```

### Secret/PII Scrubbing

Custom processor that walks all string values in the event dict and applies `sanitize_tool_result()` from `corvus/security/sanitizer.py`. Catches:
- API keys (sk-*, pk_*, AKIA*)
- OAuth/bearer tokens
- JWTs
- Connection string passwords
- Key=value credential pairs (password=, secret=, token=)
- Long hex strings (64+ chars)

This ensures no credential accidentally logged via structlog reaches console or JSON output.

### Context Binding

Using `structlog.contextvars`:

- **WebSocket connect** → `bind_contextvars(session_id=..., user=...)`
- **Per-turn start** → `bind_contextvars(dispatch_id=..., turn_id=..., agent=...)`
- **Per-turn end** → `unbind_contextvars("dispatch_id", "turn_id", "agent")`
- **WS disconnect** → `clear_contextvars()`

All log lines in the async call chain automatically include bound context.

### Logger Pattern (All Modules)

```python
import structlog

logger = structlog.get_logger(__name__)

# Keyword args, not printf:
logger.info("router_classified", agent=agent, model=model, latency_ms=elapsed)
logger.warning("sdk_interrupt_failed", session_id=sid, agent=name, exc_info=True)
```

No more custom logger names like `"corvus-gateway.router"`. Use `__name__` everywhere — the module path provides the hierarchy naturally.

## What Doesn't Change

- **EventEmitter / JSONLFileSink** — separate event bus for domain events (routing_decision, session_start, tool_call). Different purpose, stays as-is.
- **AuditLog** — security audit trail with its own JSONL format. Stays as-is.
- **TUI log file path** — `logs/tui.log` stays, just gets structlog formatting.

## Files

- **New:** `corvus/logging.py` — central configuration
- **Modified:** 57 modules — `import logging` → `import structlog`, logger calls to keyword args
- **Modified:** 3 entry points — `server.py`, `tui/app.py`, `cli/chat.py` — replace `basicConfig` with `configure_logging()`
- **New dependency:** `structlog` via `uv add`

## Constraints

- **No PII or secrets in logs.** Scrubbing processor is mandatory, not optional.
- **No lazy imports.** All `import structlog` at module level per project rules.
- **No relative imports.** Per project rules.
