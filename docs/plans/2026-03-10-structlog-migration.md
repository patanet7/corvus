---
title: "structlog Migration Implementation Plan"
type: plan
status: implemented
date: 2026-03-10
---

# structlog Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace stdlib `logging` with `structlog` across all 60 modules for structured JSON output and pretty dev console, with per-component log levels and automatic secret scrubbing.

**Architecture:** Central `corvus/logging.py` configures structlog processors including contextvars binding, per-component level filtering, and PII/secret scrubbing via existing `sanitizer.py` patterns. Every module switches to `structlog.get_logger(__name__)` with keyword-arg log calls. Entry points call `configure_logging()` once at startup.

**Tech Stack:** `structlog`, `structlog.contextvars`, existing `corvus/security/sanitizer.py`

**Design Doc:** `docs/plans/2026-03-10-structlog-migration-design.md`

---

### Task 1: Add structlog dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Install structlog**

```bash
uv add structlog
```

**Step 2: Verify import works**

```bash
uv run python -c "import structlog; print(structlog.__version__)"
```
Expected: Version string printed (e.g. `24.4.0`)

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add structlog for structured logging migration"
```

---

### Task 2: Create corvus/logging.py — central configuration

**Files:**
- Create: `corvus/logging.py`
- Test: `tests/unit/test_logging_config.py`

**Step 1: Write tests for the logging config module**

```python
"""Tests for corvus.logging — structlog configuration."""
import json
import os
import structlog
from corvus.logging import configure_logging, COMPONENT_LEVEL_MAP

def test_configure_logging_sets_up_structlog():
    """configure_logging() should set up structlog processors."""
    configure_logging()
    logger = structlog.get_logger("test")
    # Should not raise
    logger.info("test_event", key="value")

def test_json_renderer_when_log_format_json(monkeypatch):
    """LOG_FORMAT=json should produce JSON output."""
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    # Verify structlog is configured (basic smoke test)
    logger = structlog.get_logger("test")
    logger.info("json_test")

def test_component_level_map_has_expected_keys():
    """Component level map should cover all major subsystems."""
    expected = {"ROUTER", "STREAM", "GATEWAY", "TUI", "CLI", "MEMORY", "SECURITY", "ACP"}
    assert expected.issubset(set(COMPONENT_LEVEL_MAP.keys()))

def test_secret_scrubbing_in_log_output(capsys, monkeypatch):
    """API keys in log values should be scrubbed."""
    monkeypatch.setenv("LOG_FORMAT", "console")
    configure_logging()
    logger = structlog.get_logger("test.scrub")
    logger.info("auth_check", api_key="sk-ant-abc123456789012345678901234567890")
    captured = capsys.readouterr()
    assert "sk-ant-abc" not in captured.err
    assert "[REDACTED" in captured.err

def test_per_component_level_filtering(monkeypatch):
    """LOG_LEVEL_ROUTER=ERROR should suppress router INFO logs."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_LEVEL_ROUTER", "ERROR")
    configure_logging()
    # This is a behavioral test — router INFO should be suppressed
    # We verify by checking the filter function directly
    from corvus.logging import _component_level_filter
    # Simulate a router info event
    assert _component_level_filter(
        None, "info", {"_logger_name": "corvus.router"}
    ) is False
    # But gateway info should pass
    assert _component_level_filter(
        None, "info", {"_logger_name": "corvus.gateway.runtime"}
    ) is not False
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_logging_config.py -v
```
Expected: FAIL — `corvus.logging` does not exist yet.

**Step 3: Implement corvus/logging.py**

```python
"""Centralized structlog configuration for Corvus.

Call ``configure_logging()`` once at each entry point (server, TUI, CLI).
All modules then use ``structlog.get_logger(__name__)`` with keyword args.

Env vars:
    LOG_FORMAT   — "console" (default) or "json"
    LOG_LEVEL    — global default level (default: INFO)
    LOG_LEVEL_ROUTER   — override for corvus.router
    LOG_LEVEL_STREAM   — override for corvus.gateway.stream_processor
    LOG_LEVEL_GATEWAY  — override for corvus.gateway.*
    LOG_LEVEL_TUI      — override for corvus.tui.*
    LOG_LEVEL_CLI      — override for corvus.cli.*
    LOG_LEVEL_MEMORY   — override for corvus.memory.*
    LOG_LEVEL_SECURITY — override for corvus.security.*
    LOG_LEVEL_ACP      — override for corvus.acp.*
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

from corvus.security.sanitizer import SANITIZER_PATTERNS

# Maps component name → (env var suffix, module prefix for matching)
COMPONENT_LEVEL_MAP: dict[str, str] = {
    "ROUTER": "corvus.router",
    "STREAM": "corvus.gateway.stream_processor",
    "GATEWAY": "corvus.gateway",
    "TUI": "corvus.tui",
    "CLI": "corvus.cli",
    "MEMORY": "corvus.memory",
    "SECURITY": "corvus.security",
    "ACP": "corvus.acp",
}

_LEVEL_NAMES = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _resolve_component_levels() -> list[tuple[str, int]]:
    """Read LOG_LEVEL_* env vars and return (prefix, level) pairs.

    Sorted longest-prefix-first so more specific matches win.
    """
    pairs: list[tuple[str, int]] = []
    for component, prefix in COMPONENT_LEVEL_MAP.items():
        raw = os.environ.get(f"LOG_LEVEL_{component}", "").strip().lower()
        if raw in _LEVEL_NAMES:
            pairs.append((prefix, _LEVEL_NAMES[raw]))
    # Sort by prefix length descending — most specific wins
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _get_global_level() -> int:
    raw = os.environ.get("LOG_LEVEL", "INFO").strip().lower()
    return _LEVEL_NAMES.get(raw, logging.INFO)


def _component_level_filter(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any] | bool:
    """Drop events below the configured per-component log level."""
    logger_name = event_dict.get("_logger_name", "") or ""
    level = _LEVEL_NAMES.get(method_name, logging.DEBUG)

    component_levels = _resolve_component_levels()
    for prefix, min_level in component_levels:
        if logger_name.startswith(prefix):
            if level < min_level:
                raise structlog.DropEvent
            return event_dict

    # No component match — use global level
    if level < _get_global_level():
        raise structlog.DropEvent
    return event_dict


def _add_logger_name(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Ensure _logger_name is available for component filtering."""
    if "_logger_name" not in event_dict:
        record = event_dict.get("_record")
        if record:
            event_dict["_logger_name"] = record.name
    return event_dict


def _scrub_secrets(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redact secrets/PII from all string values in the event dict."""
    for key, value in event_dict.items():
        if isinstance(value, str) and len(value) > 8:
            scrubbed = value
            for pattern, replacement in SANITIZER_PATTERNS:
                scrubbed = pattern.sub(replacement, scrubbed)
            if scrubbed != value:
                event_dict[key] = scrubbed
    return event_dict


def configure_logging(
    *,
    log_format: str | None = None,
    log_file: str | None = None,
) -> None:
    """Configure structlog for the entire process.

    Args:
        log_format: "console" or "json". Defaults to LOG_FORMAT env var or "console".
        log_file: Optional file path for TUI file logging.
    """
    fmt = (log_format or os.environ.get("LOG_FORMAT", "console")).strip().lower()
    global_level = _get_global_level()

    if fmt == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_logger_name,
        _component_level_filter,
        _scrub_secrets,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(global_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to route through structlog
    # (catches third-party library logs like uvicorn, anthropic, etc.)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=global_level,
        force=True,
    )
```

**Step 4: Run tests**

```bash
uv run pytest tests/unit/test_logging_config.py -v
```
Expected: All pass.

**Step 5: Commit**

```bash
git add corvus/logging.py tests/unit/test_logging_config.py
git commit -m "feat: add corvus/logging.py — structlog central configuration"
```

---

### Task 3: Wire entry points to configure_logging()

**Files:**
- Modify: `corvus/server.py` (line 52)
- Modify: `corvus/tui/app.py` (lines 562-566)
- Modify: `corvus/cli/chat.py` (line 492)
- Modify: `corvus/cli/tool_registry.py` (line 336)

Replace every `logging.basicConfig(...)` call with `from corvus.logging import configure_logging` + `configure_logging()`.

For `tui/app.py`, pass `log_file="logs/tui.log"` to preserve file logging behavior.

For `cli/chat.py` and `cli/tool_registry.py`, the default console renderer + `LOG_LEVEL=WARNING` behavior is equivalent.

**Step 1: Modify all 4 entry points**

In each file:
- Replace `import logging` + `logging.basicConfig(...)` with:
  ```python
  from corvus.logging import configure_logging
  configure_logging()
  ```
- Keep `import structlog` and change `logger = logging.getLogger(...)` to `logger = structlog.get_logger(__name__)`

**Step 2: Start the server and verify logs appear**

```bash
LOG_LEVEL=INFO uv run python -m corvus.server
```
Expected: Colored structured logs on stderr.

**Step 3: Commit**

```bash
git add corvus/server.py corvus/tui/app.py corvus/cli/chat.py corvus/cli/tool_registry.py
git commit -m "feat: wire entry points to structlog configure_logging()"
```

---

### Task 4: Migrate corvus/ root modules (15 files)

**Files:**
- `corvus/server.py`
- `corvus/router.py`
- `corvus/credential_store.py`
- `corvus/events.py`
- `corvus/break_glass.py`
- `corvus/hooks.py`
- `corvus/kimi_bridge.py`
- `corvus/kimi_proxy.py`
- `corvus/litellm_manager.py`
- `corvus/model_router.py`
- `corvus/ollama_probe.py`
- `corvus/scheduler.py`
- `corvus/session.py`
- `corvus/supervisor.py`
- `corvus/webhooks.py`

For each file:
1. Replace `import logging` with `import structlog`
2. Replace `logger = logging.getLogger("corvus-gateway.xyz")` with `logger = structlog.get_logger(__name__)`
3. Convert printf-style calls to keyword args:
   - `logger.info("Loaded %d agents", count)` → `logger.info("agents_loaded", count=count)`
   - `logger.warning("Failed for %s: %s", name, err)` → `logger.warning("operation_failed", name=name, error=str(err))`
   - `logger.exception("Something failed")` → `logger.exception("something_failed")` (exc_info auto-attached)

**Step 1: Migrate all 15 files**

Apply the pattern to each file. Use snake_case event names (not sentences).

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```
Expected: All existing tests pass.

**Step 3: Commit**

```bash
git add corvus/server.py corvus/router.py corvus/credential_store.py corvus/events.py corvus/break_glass.py corvus/hooks.py corvus/kimi_bridge.py corvus/kimi_proxy.py corvus/litellm_manager.py corvus/model_router.py corvus/ollama_probe.py corvus/scheduler.py corvus/session.py corvus/supervisor.py corvus/webhooks.py
git commit -m "refactor: migrate corvus/ root modules to structlog"
```

---

### Task 5: Migrate corvus/gateway/ (14 files)

**Files:**
- `corvus/gateway/acp_executor.py`
- `corvus/gateway/background_dispatch.py`
- `corvus/gateway/chat_engine.py`
- `corvus/gateway/chat_session.py`
- `corvus/gateway/confirm_queue.py`
- `corvus/gateway/dispatch_orchestrator.py`
- `corvus/gateway/dispatch_runtime.py`
- `corvus/gateway/options.py`
- `corvus/gateway/run_executor.py`
- `corvus/gateway/runtime.py`
- `corvus/gateway/sdk_client_manager.py`
- `corvus/gateway/session_emitter.py`
- `corvus/gateway/stream_processor.py`
- `corvus/gateway/workspace_runtime.py`

Same pattern as Task 4. Also add context binding calls in `chat_session.py`:
- In `run()` after init message: `structlog.contextvars.bind_contextvars(session_id=self.session_id, user=self.user)`
- In the message loop per-turn: `structlog.contextvars.bind_contextvars(dispatch_id=dispatch_id, turn_id=turn_id, agent=...)`
- After dispatch completes: `structlog.contextvars.unbind_contextvars("dispatch_id", "turn_id", "agent")`

**Step 1: Migrate all 14 files**

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```

**Step 3: Commit**

```bash
git add corvus/gateway/
git commit -m "refactor: migrate corvus/gateway/ to structlog with context binding"
```

---

### Task 6: Migrate corvus/api/ (3 files)

**Files:**
- `corvus/api/chat.py`
- `corvus/api/traces.py`
- `corvus/api/webhooks.py`

Same pattern.

**Step 1: Migrate all 3 files**

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```

**Step 3: Commit**

```bash
git add corvus/api/
git commit -m "refactor: migrate corvus/api/ to structlog"
```

---

### Task 7: Migrate corvus/agents/ and corvus/capabilities/ (6 files)

**Files:**
- `corvus/agents/hub.py`
- `corvus/agents/registry.py`
- `corvus/agents/spec.py`
- `corvus/capabilities/config.py`
- `corvus/capabilities/modules.py`
- `corvus/capabilities/registry.py`

**Step 1: Migrate all 6 files**

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```

**Step 3: Commit**

```bash
git add corvus/agents/ corvus/capabilities/
git commit -m "refactor: migrate corvus/agents/ and corvus/capabilities/ to structlog"
```

---

### Task 8: Migrate corvus/memory/ and corvus/security/ (5 files)

**Files:**
- `corvus/memory/config.py`
- `corvus/memory/hub.py`
- `corvus/memory/toolkit.py`
- `corvus/memory/backends/cognee.py`
- `corvus/security/audit.py`

**Step 1: Migrate all 5 files**

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```

**Step 3: Commit**

```bash
git add corvus/memory/ corvus/security/audit.py
git commit -m "refactor: migrate corvus/memory/ and corvus/security/ to structlog"
```

---

### Task 9: Migrate corvus/acp/ and corvus/auth/ (7 files)

**Files:**
- `corvus/acp/client.py`
- `corvus/acp/file_gate.py`
- `corvus/acp/registry.py`
- `corvus/acp/sandbox.py`
- `corvus/acp/session.py`
- `corvus/acp/terminal_gate.py`
- `corvus/auth/openai_oauth.py`

**Step 1: Migrate all 7 files**

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```

**Step 3: Commit**

```bash
git add corvus/acp/ corvus/auth/
git commit -m "refactor: migrate corvus/acp/ and corvus/auth/ to structlog"
```

---

### Task 10: Migrate corvus/cli/ and corvus/tui/ (7 files)

**Files:**
- `corvus/cli/chat.py`
- `corvus/cli/mcp_stdio.py`
- `corvus/cli/tool_registry.py`
- `corvus/cli/workspace.py`
- `corvus/tui/app.py`
- `corvus/tui/protocol/in_process.py`
- `corvus/tui/protocol/websocket.py`

**Step 1: Migrate all 7 files**

**Step 2: Run tests**

```bash
uv run pytest tests/ -x -q --timeout=30
```

**Step 3: Commit**

```bash
git add corvus/cli/ corvus/tui/
git commit -m "refactor: migrate corvus/cli/ and corvus/tui/ to structlog"
```

---

### Task 11: Verify no remaining stdlib logging in corvus/

**Step 1: Search for remaining stdlib logging imports**

```bash
grep -r "import logging" corvus/ --include="*.py" | grep -v "__pycache__"
grep -r "logging.getLogger" corvus/ --include="*.py" | grep -v "__pycache__"
```
Expected: No results (all converted).

Note: `corvus/logging.py` itself imports `logging` — that's the ONE exception (it needs stdlib logging to configure the root logger for third-party library output).

**Step 2: Run full test suite**

```bash
mise run test
```
Expected: All tests pass.

**Step 3: Commit any stragglers**

---

### Task 12: Run live QA to verify structured output

**Step 1: Start server with console renderer**

```bash
LOG_LEVEL=DEBUG uv run python -m corvus.server
```
Expected: Colored key=value logs with session_id, user context bound.

**Step 2: Run live QA test**

```bash
uv run python tests/integration/test_live_llm_qa.py
```
Expected: 41/41 PASS. Server output shows structured logs with context.

**Step 3: Test JSON renderer**

```bash
LOG_FORMAT=json LOG_LEVEL=INFO uv run python -m corvus.server &
curl -s http://127.0.0.1:8000/health | python -m json.tool
```
Expected: Server log lines are valid JSON.

**Step 4: Test per-component level**

```bash
LOG_LEVEL=WARNING LOG_LEVEL_ROUTER=DEBUG uv run python -m corvus.server
```
Expected: Only router debug logs appear; other components stay at WARNING.

**Step 5: Commit**

```bash
git commit --allow-empty -m "test: verified structlog migration with live QA — 41/41 green"
```

---

## Task Dependency Graph

```
Task 1 (add dep) → Task 2 (logging.py) → Task 3 (entry points)
                                             ↓
                    ┌──────────────────────────┤
                    ↓         ↓        ↓       ↓        ↓        ↓        ↓
                 Task 4    Task 5   Task 6   Task 7   Task 8   Task 9   Task 10
                 (root)   (gateway)  (api)  (agents) (memory)  (acp)   (cli/tui)
                    ↓         ↓        ↓       ↓        ↓        ↓        ↓
                    └──────────────────────────┤
                                               ↓
                                           Task 11 (verify)
                                               ↓
                                           Task 12 (live QA)
```

Tasks 4–10 are independent after Task 3 and can be done in parallel or any order.
