# ChatSession Extraction — Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract the 1,256-line `corvus/api/chat.py` closure soup into a `ChatSession` class with `TurnContext` dataclass, eliminating nested closures and enabling per-method behavioral testing.

**Architecture:** Convert `websocket_chat()` into a thin factory that instantiates `ChatSession`. Session-lifetime state becomes instance attributes; per-turn state is scoped via a `TurnContext` dataclass. The `_send`, `_execute_agent_run`, and `_dispatch_control_listener` closures become class methods. Repeated payload construction and error exit paths are consolidated via `_base_payload()` and `_emit_run_failure()` helpers.

**Tech Stack:** Python 3.13, FastAPI WebSocket, claude_agent_sdk, SQLite session store, pytest (NO MOCKS)

---

## Existing Architecture

```
corvus/api/chat.py (1,256 lines)
  └── websocket_chat() — single massive async function
       ├── _send()                      (lines 239-305, closure)
       ├── _execute_agent_run()         (lines 472-1057, closure, ~585 lines)
       │    ├── _emit_phase()           (nested closure)
       │    └── _run_hook_ws_callback() (nested closure)
       └── _dispatch_control_listener() (lines 1059-1112, closure)
```

## Target Architecture

```
corvus/api/chat.py (~80 lines)
  └── websocket_chat() — auth + session resume + ChatSession().run()

corvus/gateway/chat_session.py (~650 lines)
  ├── TurnContext (dataclass, per-turn state)
  └── ChatSession (class)
       ├── __init__()                  — session-lifetime state
       ├── run()                       — main message loop
       ├── send()                      — WS send + persist + trace (orchestrator)
       │    ├── _ws_send()             — WebSocket send under lock
       │    ├── _persist_session_event() — session events table
       │    ├── _persist_run_event()   — run events table
       │    └── _publish_trace()       — TraceHub fan-out
       ├── execute_agent_run()         — full run lifecycle
       │    ├── _base_payload()        — shared payload dict builder
       │    ├── _emit_phase()          — phase + task_progress events
       │    └── _emit_run_failure()    — consolidated error exit
       └── dispatch_control_listener() — interrupt/ping/confirm during dispatch
```

## Files Changed

| File | Action | Notes |
|------|--------|-------|
| `corvus/gateway/chat_session.py` | Create | `ChatSession` class + `TurnContext` dataclass |
| `corvus/api/chat.py` | Rewrite | Slim to ~80 lines: router, auth, session resume, ChatSession instantiation |
| `corvus/gateway/__init__.py` | Modify | Add `ChatSession` to exports |
| `tests/gateway/test_chat_session.py` | Create | Behavioral tests for ChatSession methods |
| `tests/gateway/test_chat_no_llm.py` | Verify | Must still pass unchanged (imports from `corvus.server`) |
| `tests/gateway/test_frontend_backend_contracts.py` | Verify | Must still pass unchanged |

## Constraints

- NO MOCKS (behavioral tests only)
- NO LAZY IMPORTS
- NO RELATIVE IMPORTS
- All test output → `tests/output/TIMESTAMP_test_XXX_results.log`
- Existing WS protocol contracts must not change (message types, payload shapes)
- `background_dispatch.py` is NOT touched (Phase 2)

---

### Task 1: Create TurnContext dataclass

**Files:**
- Create: `corvus/gateway/chat_session.py`
- Test: `tests/gateway/test_chat_session.py`

**Step 1: Write the failing test**

```python
"""Behavioral tests for ChatSession class and TurnContext."""

from __future__ import annotations

import asyncio

from corvus.gateway.chat_session import TurnContext


class TestTurnContext:
    def test_turn_context_construction(self) -> None:
        interrupt = asyncio.Event()
        ctx = TurnContext(
            dispatch_id="d-123",
            turn_id="t-456",
            dispatch_interrupted=interrupt,
            user_model=None,
            requires_tools=False,
        )
        assert ctx.dispatch_id == "d-123"
        assert ctx.turn_id == "t-456"
        assert ctx.dispatch_interrupted is interrupt
        assert ctx.user_model is None
        assert ctx.requires_tools is False

    def test_turn_context_with_model_and_tools(self) -> None:
        ctx = TurnContext(
            dispatch_id="d-abc",
            turn_id="t-def",
            dispatch_interrupted=asyncio.Event(),
            user_model="ollama/llama3",
            requires_tools=True,
        )
        assert ctx.user_model == "ollama/llama3"
        assert ctx.requires_tools is True
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestTurnContext -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.gateway.chat_session'`

**Step 3: Write minimal implementation**

Create `corvus/gateway/chat_session.py` with just the `TurnContext` dataclass:

```python
"""ChatSession class — WebSocket chat lifecycle extracted from closure soup.

Converts the deeply nested closures in corvus/api/chat.py into a class with
explicit instance state. Session-lifetime state lives on the instance;
per-turn state is scoped via TurnContext.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class TurnContext:
    """Per-turn dispatch state — created fresh each turn, passed to methods."""

    dispatch_id: str
    turn_id: str
    dispatch_interrupted: asyncio.Event
    user_model: str | None
    requires_tools: bool
```

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestTurnContext -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add corvus/gateway/chat_session.py tests/gateway/test_chat_session.py
git commit -m "feat: add TurnContext dataclass for per-turn dispatch state"
```

---

### Task 2: ChatSession scaffold with __init__ and send()

**Files:**
- Modify: `corvus/gateway/chat_session.py`
- Test: `tests/gateway/test_chat_session.py`

**Step 1: Write the failing tests**

Add to `tests/gateway/test_chat_session.py`:

```python
import importlib
import json

import pytest

SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed",
)


@skip_no_sdk
class TestChatSessionSend:
    @pytest.fixture
    def runtime(self):
        from corvus.gateway.runtime import build_runtime
        return build_runtime()

    @pytest.fixture
    def session(self, runtime):
        from corvus.gateway.chat_session import ChatSession
        return ChatSession(
            runtime=runtime,
            websocket=None,
            user="patanet7",
            session_id="test-send-session",
        )

    def test_chat_session_attributes(self, session) -> None:
        assert session.user == "patanet7"
        assert session.session_id == "test-send-session"
        assert session.runtime is not None
        assert session.current_turn_id is None

    def test_persist_session_event_writes_to_session_mgr(self, runtime, session) -> None:
        """Verify _persist_session_event writes to the real session store."""
        runtime.session_mgr.start(
            "test-send-session",
            user="patanet7",
        )
        session.current_turn_id = "turn-1"
        session._persist_session_event(
            event_type="dispatch_start",
            payload={"type": "dispatch_start", "dispatch_id": "d-1"},
            turn_id="turn-1",
        )
        events = runtime.session_mgr.get_events("test-send-session")
        assert len(events) >= 1
        assert events[-1]["event_type"] == "dispatch_start"
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestChatSessionSend -v`
Expected: FAIL with `ImportError: cannot import name 'ChatSession'`

**Step 3: Write implementation**

Add to `corvus/gateway/chat_session.py` after `TurnContext`:

```python
import json
import logging

from fastapi import WebSocket

from corvus.gateway.runtime import GatewayRuntime
from corvus.session import SessionTranscript

logger = logging.getLogger("corvus-gateway")

_PERSISTED_SESSION_EVENT_TYPES = {
    "dispatch_start",
    "dispatch_plan",
    "dispatch_complete",
    "run_start",
    "run_phase",
    "run_output_chunk",
    "run_complete",
    "task_start",
    "task_progress",
    "task_complete",
    "tool_start",
    "tool_result",
    "confirm_request",
    "confirm_response",
    "interrupt_ack",
}

_PERSISTED_RUN_EVENT_TYPES = {
    "run_start",
    "run_phase",
    "run_output_chunk",
    "run_complete",
    "tool_start",
    "tool_result",
    "confirm_request",
    "confirm_response",
}

_TRACE_EVENT_TYPES = _PERSISTED_SESSION_EVENT_TYPES | {
    "routing",
    "agent_status",
    "error",
}


class ChatSession:
    """WebSocket chat session lifecycle.

    Replaces the closure soup in websocket_chat() with explicit instance state.
    Session-lifetime state lives on the instance; per-turn state is scoped via
    TurnContext passed to methods.
    """

    def __init__(
        self,
        *,
        runtime: GatewayRuntime,
        websocket: WebSocket | None,
        user: str,
        session_id: str,
    ) -> None:
        self.runtime = runtime
        self.websocket = websocket
        self.user = user
        self.session_id = session_id
        self.send_lock = asyncio.Lock()
        self.current_turn_id: str | None = None
        self.transcript = SessionTranscript(
            user=user,
            session_id=session_id,
            messages=[],
        )

    # --- Send sub-methods (decomposed from the monolithic _send closure) ---

    async def _ws_send(self, payload: dict) -> None:
        """Send payload over WebSocket under lock."""
        if self.websocket is None:
            return
        async with self.send_lock:
            await self.websocket.send_json(payload)

    def _persist_session_event(
        self,
        *,
        event_type: str,
        payload: dict,
        turn_id: str | None,
    ) -> None:
        """Persist to session events table."""
        try:
            self.runtime.session_mgr.add_event(
                session_id=self.session_id,
                turn_id=turn_id or self.current_turn_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "Failed to persist session event: session_id=%s type=%s",
                self.session_id,
                event_type,
            )

    def _persist_run_event(
        self,
        *,
        run_id: str,
        dispatch_id: str,
        event_type: str,
        payload: dict,
        turn_id: str | None,
    ) -> None:
        """Persist to run events table."""
        try:
            self.runtime.session_mgr.add_run_event(
                run_id,
                dispatch_id=dispatch_id,
                session_id=self.session_id,
                turn_id=turn_id or self.current_turn_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "Failed to persist run event: run_id=%s type=%s",
                run_id,
                event_type,
            )

    async def _publish_trace(
        self,
        *,
        event_type: str,
        payload: dict,
        dispatch_id: str | None,
        run_id: str | None,
        turn_id: str | None,
    ) -> None:
        """Publish to TraceHub for live observability."""
        trace_dispatch_id = dispatch_id or _optional_str(payload.get("dispatch_id"))
        trace_run_id = run_id or _optional_str(payload.get("run_id"))
        trace_turn_id = turn_id or self.current_turn_id or _optional_str(payload.get("turn_id"))
        try:
            trace_row = self.runtime.session_mgr.add_trace_event(
                source_app=_trace_source_app(event_type, payload),
                session_id=self.session_id,
                dispatch_id=trace_dispatch_id,
                run_id=trace_run_id,
                turn_id=trace_turn_id,
                hook_event_type=event_type,
                payload=payload,
                summary=_trace_summary(event_type, payload),
                model_name=_optional_str(payload.get("model")),
            )
            await self.runtime.trace_hub.publish(user=self.user, event=trace_row)
        except Exception:
            logger.exception(
                "Failed to persist/publish trace event: session_id=%s type=%s",
                self.session_id,
                event_type,
            )

    async def send(
        self,
        payload: dict,
        *,
        persist: bool = False,
        run_id: str | None = None,
        dispatch_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        """Orchestrate: ws_send + optional persist + optional trace."""
        await self._ws_send(payload)
        event_type = str(payload.get("type", ""))
        if persist and event_type in _PERSISTED_SESSION_EVENT_TYPES:
            self._persist_session_event(
                event_type=event_type,
                payload=payload,
                turn_id=turn_id,
            )
        if run_id and dispatch_id and event_type in _PERSISTED_RUN_EVENT_TYPES and persist:
            self._persist_run_event(
                run_id=run_id,
                dispatch_id=dispatch_id,
                event_type=event_type,
                payload=payload,
                turn_id=turn_id,
            )
        should_trace = event_type in _TRACE_EVENT_TYPES and (
            persist or event_type in {"routing", "agent_status", "error"}
        )
        if should_trace:
            await self._publish_trace(
                event_type=event_type,
                payload=payload,
                dispatch_id=dispatch_id,
                run_id=run_id,
                turn_id=turn_id,
            )
```

Also add the module-level helper functions (moved from chat.py):

```python
def _preview_summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


def _trace_source_app(event_type: str, payload: dict) -> str:
    if agent := _optional_str(payload.get("agent")):
        return agent
    if event_type in {"dispatch_start", "dispatch_plan", "dispatch_complete", "routing"}:
        return "router"
    return "gateway"


def _trace_summary(event_type: str, payload: dict) -> str | None:
    if summary := _optional_str(payload.get("summary")):
        return _preview_summary(summary, limit=220)
    if event_type == "run_output_chunk":
        if content := _optional_str(payload.get("content")):
            return _preview_summary(content, limit=220)
        if payload.get("final") is True:
            return "Final output marker"
    if message := _optional_str(payload.get("message")):
        return _preview_summary(message, limit=220)
    if event_type == "tool_start":
        if tool := _optional_str(payload.get("tool")):
            return f"Tool start: {tool}"
    if event_type == "tool_result":
        status = _optional_str(payload.get("status")) or "success"
        return f"Tool result ({status})"
    if event_type == "confirm_request":
        if tool := _optional_str(payload.get("tool")):
            return f"Confirm request: {tool}"
    return None
```

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add corvus/gateway/chat_session.py tests/gateway/test_chat_session.py
git commit -m "feat: ChatSession class with send() and decomposed event persistence"
```

---

### Task 3: Payload builder and run failure helper

**Files:**
- Modify: `corvus/gateway/chat_session.py`
- Test: `tests/gateway/test_chat_session.py`

**Step 1: Write the failing tests**

```python
class TestPayloadBuilders:
    def test_base_payload_includes_required_fields(self) -> None:
        from corvus.gateway.chat_session import ChatSession, TurnContext

        ctx = TurnContext(
            dispatch_id="d-1",
            turn_id="t-1",
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=False,
        )
        route_payload = {"task_type": "chat", "subtask_id": None, "skill": None, "instruction": None, "route_index": 0}
        result = ChatSession._base_payload(
            turn=ctx,
            run_id="r-1",
            task_id="task-r1",
            agent="general",
            route_payload=route_payload,
            session_id="s-1",
        )
        assert result["dispatch_id"] == "d-1"
        assert result["run_id"] == "r-1"
        assert result["task_id"] == "task-r1"
        assert result["session_id"] == "s-1"
        assert result["turn_id"] == "t-1"
        assert result["agent"] == "general"
        assert result["task_type"] == "chat"
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestPayloadBuilders -v`
Expected: FAIL with `AttributeError: type object 'ChatSession' has no attribute '_base_payload'`

**Step 3: Write implementation**

Add to `ChatSession` class:

```python
    @staticmethod
    def _base_payload(
        *,
        turn: TurnContext,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        session_id: str,
    ) -> dict:
        """Build the common payload dict shared by all run events."""
        return {
            "dispatch_id": turn.dispatch_id,
            "run_id": run_id,
            "task_id": task_id,
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "agent": agent,
            **route_payload,
        }

    async def _emit_phase(
        self,
        turn: TurnContext,
        *,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        phase: str,
        summary: str,
    ) -> None:
        """Emit run_phase + optional task_progress events."""
        base = self._base_payload(
            turn=turn, run_id=run_id, task_id=task_id,
            agent=agent, route_payload=route_payload, session_id=self.session_id,
        )
        phase_status = "streaming" if phase == "executing" else "error" if phase == "error" else "thinking"
        await self.send(
            {"type": "run_phase", **base, "phase": phase, "summary": summary},
            persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
        )
        if phase not in {"done", "error", "interrupted"}:
            await self.send(
                {"type": "task_progress", "task_id": task_id, "agent": agent,
                 "status": phase_status, "summary": summary,
                 "session_id": self.session_id, "turn_id": turn.turn_id, **route_payload},
                persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
            )

    async def _emit_run_failure(
        self,
        turn: TurnContext,
        *,
        run_id: str,
        task_id: str,
        agent: str,
        route_payload: dict,
        error_type: str,
        summary: str,
        context_limit: int,
    ) -> dict:
        """Consolidated error exit: emit events, update run record, return error dict."""
        from datetime import UTC, datetime

        base = self._base_payload(
            turn=turn, run_id=run_id, task_id=task_id,
            agent=agent, route_payload=route_payload, session_id=self.session_id,
        )
        await self._emit_phase(
            turn, run_id=run_id, task_id=task_id, agent=agent,
            route_payload=route_payload, phase="error", summary=summary,
        )
        await self.send(
            {"type": "run_complete", **base, "result": "error", "summary": summary,
             "cost_usd": 0.0, "tokens_used": 0, "context_limit": context_limit, "context_pct": 0.0},
            persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
        )
        await self.send(
            {"type": "task_complete", "task_id": task_id, "agent": agent,
             "result": "error", "summary": summary, "cost_usd": 0.0,
             "session_id": self.session_id, "turn_id": turn.turn_id, **route_payload},
            persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
        )
        self.runtime.session_mgr.update_agent_run(
            run_id, status="error", summary=summary,
            error=error_type, completed_at=datetime.now(UTC),
        )
        return {"result": "error", "cost_usd": 0.0, "tokens_used": 0, "context_pct": 0.0}
```

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add corvus/gateway/chat_session.py tests/gateway/test_chat_session.py
git commit -m "feat: add _base_payload, _emit_phase, and _emit_run_failure helpers to ChatSession"
```

---

### Task 4: execute_agent_run() method

**Files:**
- Modify: `corvus/gateway/chat_session.py`
- Test: `tests/gateway/test_chat_session.py`

**Step 1: Write the failing test**

```python
@skip_no_sdk
class TestChatSessionExecuteAgentRun:
    @pytest.fixture
    def runtime(self):
        from corvus.gateway.runtime import build_runtime
        return build_runtime()

    @pytest.fixture
    def session(self, runtime):
        from corvus.gateway.chat_session import ChatSession
        runtime.session_mgr.start("test-run-session", user="patanet7")
        return ChatSession(
            runtime=runtime,
            websocket=None,
            user="patanet7",
            session_id="test-run-session",
        )

    def test_execute_agent_run_exists_and_is_async(self, session) -> None:
        """execute_agent_run is an async method on ChatSession."""
        import inspect
        assert hasattr(session, "execute_agent_run")
        assert inspect.iscoroutinefunction(session.execute_agent_run)

    def test_execute_agent_run_signature_matches_run_executor_protocol(self, session) -> None:
        """Method accepts (route, *, route_index) matching RunExecutor protocol."""
        import inspect
        sig = inspect.signature(session.execute_agent_run)
        params = list(sig.parameters.keys())
        assert "route" in params
        assert "route_index" in params
        # route_index must be keyword-only
        ri_param = sig.parameters["route_index"]
        assert ri_param.kind == inspect.Parameter.KEYWORD_ONLY
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestChatSessionExecuteAgentRun -v`
Expected: FAIL with `AttributeError: 'ChatSession' object has no attribute 'execute_agent_run'`

**Step 3: Write implementation**

Add the `execute_agent_run` method to `ChatSession`. This is the core extraction — moving lines 472-1057 from `chat.py` into a method that uses `self.*` and `self._current_turn` (a `TurnContext`) instead of closure variables. The method signature matches the `RunExecutor` protocol from `dispatch_runtime.py`:

```python
    async def execute_agent_run(self, route: TaskRoute, *, route_index: int) -> dict:
        """Execute a single agent run — model resolve → SDK query → stream → complete.

        Replaces the 585-line _execute_agent_run closure from websocket_chat().
        Uses self._current_turn for per-turn state instead of closure capture.
        """
        turn = self._current_turn
        assert turn is not None, "execute_agent_run called outside of a turn"

        agent_name = route.agent
        run_id = str(uuid.uuid4())
        task_id = f"task-{run_id[:8]}"
        self.transcript.record_agent(agent_name)
        route_payload = {
            "task_type": route.task_type,
            "subtask_id": route.subtask_id,
            "skill": route.skill,
            "instruction": route.instruction,
            "route_index": route_index,
        }
        run_message = route.prompt
        requested_model = route.requested_model or turn.user_model

        backend_name, active_model = resolve_backend_and_model(
            runtime=self.runtime, agent_name=agent_name, requested_model=requested_model,
        )
        active_model_id = ui_model_id(backend_name, active_model)
        model_info = self.runtime.model_router.get_model_info(active_model_id)
        chunk_index = 0
        response_parts: list[str] = []
        assistant_summary = ""
        total_cost = 0.0
        tokens_used = 0
        context_limit = self.runtime.model_router.get_context_limit(active_model)
        context_pct = 0.0

        base = self._base_payload(
            turn=turn, run_id=run_id, task_id=task_id,
            agent=agent_name, route_payload=route_payload, session_id=self.session_id,
        )

        try:
            self.runtime.session_mgr.start_agent_run(
                run_id, dispatch_id=turn.dispatch_id, session_id=self.session_id,
                turn_id=turn.turn_id, agent=agent_name, backend=backend_name,
                model=active_model_id, task_type=route.task_type,
                subtask_id=route.subtask_id, skill=route.skill, status="queued",
            )
        except Exception:
            logger.exception("Failed to persist run row run_id=%s", run_id)

        await self.send({"type": "routing", "agent": agent_name, "model": active_model_id, **route_payload})
        await self.send(
            {"type": "run_start", **base, "backend": backend_name, "model": active_model_id, "status": "queued"},
            persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
        )
        await self.send(
            {"type": "task_start", "task_id": task_id, "agent": agent_name,
             "description": _preview_summary(run_message, limit=120),
             "session_id": self.session_id, "turn_id": turn.turn_id, **route_payload},
            persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
        )

        try:
            await self._emit_phase(
                turn, run_id=run_id, task_id=task_id, agent=agent_name,
                route_payload=route_payload, phase="routing", summary="Routing and model validation",
            )
            await self.runtime.emitter.emit(
                "routing_decision", agent=agent_name, backend=backend_name,
                source="websocket", query_preview=run_message[:200],
                task_type=route.task_type, subtask_id=route.subtask_id, skill=route.skill,
            )
            if turn.dispatch_interrupted.is_set():
                raise asyncio.CancelledError

            # Model capability mismatch check
            if turn.requires_tools and model_info and not model_info.supports_tools:
                fallback_backend, fallback_model = resolve_backend_and_model(
                    runtime=self.runtime, agent_name=agent_name, requested_model=None,
                )
                suggested_model = ui_model_id(fallback_backend, fallback_model)
                if suggested_model == active_model_id:
                    suggested_model = ui_default_model(self.runtime)
                await self.send({
                    "type": "error", "error": "model_capability_mismatch",
                    "model": active_model_id, "capability": "tools",
                    "suggested_model": suggested_model,
                    "message": f"Model `{active_model_id}` does not support tool-enabled turns. "
                               f"Switch to `{suggested_model}` and retry.",
                    "agent": agent_name, **route_payload,
                })
                return await self._emit_run_failure(
                    turn, run_id=run_id, task_id=task_id, agent=agent_name,
                    route_payload=route_payload, error_type="model_capability_mismatch",
                    summary="Blocked: selected model cannot execute tool-enabled turn.",
                    context_limit=context_limit,
                )

            backend_env = self.runtime.client_pool.build_env(backend_name)

            async def _run_hook_ws_callback(payload: dict) -> None:
                enriched = dict(payload)
                enriched.setdefault("dispatch_id", turn.dispatch_id)
                enriched.setdefault("run_id", run_id)
                enriched.setdefault("task_id", task_id)
                enriched.setdefault("session_id", self.session_id)
                enriched.setdefault("turn_id", turn.turn_id)
                enriched.setdefault("agent", agent_name)
                enriched.setdefault("task_type", route.task_type)
                enriched.setdefault("subtask_id", route.subtask_id)
                enriched.setdefault("skill", route.skill)
                enriched.setdefault("instruction", route.instruction)
                enriched.setdefault("route_index", route_index)
                await self.send(
                    enriched, persist=True, run_id=run_id,
                    dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                )

            client_options = build_backend_options(
                runtime=self.runtime, user=self.user, websocket=self.websocket,
                backend_name=backend_name, backend_env=backend_env,
                active_model=active_model, ws_callback=_run_hook_ws_callback,
                allow_secret_access=self.runtime.break_glass.is_active(
                    user=self.user, session_id=self.session_id,
                ),
            )

            async with ClaudeSDKClient(options=client_options) as client:
                try:
                    await client.set_model(active_model)
                except Exception as exc:
                    logger.warning("Failed to set model '%s': %s", active_model, exc)
                    await self.send({
                        "type": "error", "error": "model_unavailable",
                        "model": active_model_id,
                        "message": f"Selected model unavailable: {active_model_id}",
                        "agent": agent_name, **route_payload,
                    })
                    return await self._emit_run_failure(
                        turn, run_id=run_id, task_id=task_id, agent=agent_name,
                        route_payload=route_payload, error_type="model_unavailable",
                        summary="Selected model unavailable.",
                        context_limit=context_limit,
                    )

                await self._emit_phase(
                    turn, run_id=run_id, task_id=task_id, agent=agent_name,
                    route_payload=route_payload, phase="planning", summary="Preparing execution plan",
                )
                await self._emit_phase(
                    turn, run_id=run_id, task_id=task_id, agent=agent_name,
                    route_payload=route_payload, phase="executing", summary="Agent execution started",
                )

                await client.query(run_message, session_id=self.session_id)
                async for sdk_message in client.receive_response():
                    if turn.dispatch_interrupted.is_set():
                        raise asyncio.CancelledError
                    if isinstance(sdk_message, AssistantMessage):
                        for block in sdk_message.content:
                            if not isinstance(block, TextBlock):
                                continue
                            response_parts.append(block.text)
                            assistant_summary = _preview_summary(" ".join(response_parts), limit=140)
                            await self.send(
                                {"type": "run_output_chunk", **base, "model": active_model_id,
                                 "chunk_index": chunk_index, "content": block.text, "final": False},
                                persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                            )
                            chunk_index += 1
                            await self.send(
                                {"type": "text", "content": block.text, "agent": agent_name,
                                 "model": active_model_id, "run_id": run_id, **route_payload},
                            )
                            await self.send(
                                {"type": "task_progress", "task_id": task_id, "agent": agent_name,
                                 "status": "streaming",
                                 "summary": assistant_summary or "Streaming response...",
                                 "session_id": self.session_id, "turn_id": turn.turn_id, **route_payload},
                                persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                            )
                    elif isinstance(sdk_message, ResultMessage):
                        tokens_used = getattr(sdk_message, "total_input_tokens", 0) + getattr(
                            sdk_message, "total_output_tokens", 0,
                        )
                        total_cost = float(getattr(sdk_message, "total_cost_usd", 0.0))
                        context_pct = (
                            round((tokens_used / context_limit) * 100, 1) if context_limit > 0 else 0.0
                        )

                await self._emit_phase(
                    turn, run_id=run_id, task_id=task_id, agent=agent_name,
                    route_payload=route_payload, phase="compacting",
                    summary="Compacting and finalizing response",
                )
                await self.send(
                    {"type": "run_output_chunk", **base, "model": active_model_id,
                     "chunk_index": chunk_index, "content": "", "final": True,
                     "tokens_used": tokens_used, "cost_usd": total_cost,
                     "context_limit": context_limit, "context_pct": context_pct},
                    persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                )

                if response_parts:
                    assistant_text = " ".join(response_parts)
                    self.transcript.messages.append({"role": "assistant", "content": assistant_text})
                    self.runtime.session_mgr.add_message(
                        session_id=self.session_id, role="assistant",
                        content=assistant_text, agent=agent_name, model=active_model_id,
                    )

                await self.send(
                    {"type": "run_complete", **base, "result": "success",
                     "summary": assistant_summary or "Completed",
                     "cost_usd": total_cost, "tokens_used": tokens_used,
                     "context_limit": context_limit, "context_pct": context_pct},
                    persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                )
                await self.send(
                    {"type": "task_complete", "task_id": task_id, "agent": agent_name,
                     "result": "success", "summary": assistant_summary or "Completed",
                     "cost_usd": total_cost, "session_id": self.session_id,
                     "turn_id": turn.turn_id, **route_payload},
                    persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                )

                self.runtime.session_mgr.update_agent_run(
                    run_id, status="done", summary=assistant_summary or "Completed",
                    cost_usd=total_cost, tokens_used=tokens_used,
                    context_limit=context_limit, context_pct=context_pct,
                    completed_at=datetime.now(UTC),
                )
                return {
                    "result": "success", "cost_usd": total_cost,
                    "tokens_used": tokens_used, "context_pct": context_pct,
                    "context_limit": context_limit,
                }
        except asyncio.CancelledError:
            await self._emit_phase(
                turn, run_id=run_id, task_id=task_id, agent=agent_name,
                route_payload=route_payload, phase="interrupted", summary="Interrupted by user",
            )
            await self.send(
                {"type": "run_complete", **base, "result": "interrupted",
                 "summary": "Interrupted by user.", "cost_usd": total_cost,
                 "tokens_used": tokens_used, "context_limit": context_limit,
                 "context_pct": context_pct},
                persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
            )
            await self.send(
                {"type": "task_complete", "task_id": task_id, "agent": agent_name,
                 "result": "interrupted", "summary": "Interrupted by user.",
                 "cost_usd": total_cost, "session_id": self.session_id,
                 "turn_id": turn.turn_id, **route_payload},
                persist=True, run_id=run_id, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
            )
            self.runtime.session_mgr.update_agent_run(
                run_id, status="interrupted", summary="Interrupted by user",
                completed_at=datetime.now(UTC),
            )
            return {
                "result": "interrupted", "cost_usd": total_cost,
                "tokens_used": tokens_used, "context_pct": context_pct,
                "context_limit": context_limit,
            }
        except Exception as exc:
            logger.exception("Error processing run agent=%s", agent_name)
            safe_msg = type(exc).__name__
            await self.send({
                "type": "error", "message": f"Internal error: {safe_msg}",
                "agent": agent_name, **route_payload,
            })
            return await self._emit_run_failure(
                turn, run_id=run_id, task_id=task_id, agent=agent_name,
                route_payload=route_payload, error_type=safe_msg,
                summary="Internal error during task execution.",
                context_limit=context_limit,
            )
```

Also add a `_current_turn` attribute initialized to `None` in `__init__`:

```python
self._current_turn: TurnContext | None = None
```

And add the necessary imports at the top of `chat_session.py`:

```python
import uuid
from datetime import UTC, datetime

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

from corvus.gateway.options import (
    build_backend_options,
    resolve_backend_and_model,
    ui_default_model,
    ui_model_id,
)
from corvus.gateway.task_planner import TaskRoute
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add corvus/gateway/chat_session.py tests/gateway/test_chat_session.py
git commit -m "feat: add execute_agent_run method to ChatSession — 585-line closure extracted"
```

---

### Task 5: dispatch_control_listener() method

**Files:**
- Modify: `corvus/gateway/chat_session.py`
- Test: `tests/gateway/test_chat_session.py`

**Step 1: Write the failing test**

```python
class TestDispatchControlListener:
    def test_dispatch_control_listener_exists_and_is_async(self) -> None:
        import inspect
        from corvus.gateway.chat_session import ChatSession
        assert hasattr(ChatSession, "dispatch_control_listener")
        assert inspect.iscoroutinefunction(ChatSession.dispatch_control_listener)
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestDispatchControlListener -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `ChatSession`:

```python
    async def dispatch_control_listener(self) -> None:
        """Listen for interrupt/ping/confirm messages during active dispatch.

        Runs as a concurrent task alongside execute_dispatch_runs. Reads from
        the WebSocket and handles control messages until the dispatch completes
        or the user sends an interrupt.
        """
        turn = self._current_turn
        assert turn is not None
        assert self.websocket is not None

        while not turn.dispatch_interrupted.is_set():
            control_data = await self.websocket.receive_text()
            try:
                control_msg = json.loads(control_data)
            except json.JSONDecodeError:
                await self.send({"type": "error", "message": "Invalid JSON"})
                continue

            control_type = control_msg.get("type")
            if control_type == "interrupt":
                self.runtime.dispatch_controls.request_interrupt(
                    turn.dispatch_id, user=self.user, source="ws",
                )
                logger.info("User interrupted dispatch %s", turn.dispatch_id)
                await self.runtime.emitter.emit(
                    "session_interrupt", user=self.user, session_id=self.session_id,
                )
                await self.send(
                    {"type": "interrupt_ack", "dispatch_id": turn.dispatch_id,
                     "session_id": self.session_id, "turn_id": turn.turn_id,
                     "status": "interrupting"},
                    persist=True, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                )
                return
            if control_type == "ping":
                await self.send({"type": "pong"})
                continue
            if control_type == "confirm_response":
                call_id = control_msg.get("tool_call_id")
                approved = control_msg.get("approved", False)
                await self.send(
                    {"type": "confirm_response", "tool_call_id": call_id,
                     "approved": bool(approved)},
                    persist=True, dispatch_id=turn.dispatch_id, turn_id=turn.turn_id,
                )
                continue
            if control_msg.get("message"):
                await self.send({
                    "type": "error", "error": "dispatch_in_progress",
                    "message": "Dispatch already in progress; wait or interrupt before sending a new prompt.",
                })
                continue
            await self.send({"type": "error", "message": "Unsupported control message while dispatch is active"})
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add corvus/gateway/chat_session.py tests/gateway/test_chat_session.py
git commit -m "feat: add dispatch_control_listener method to ChatSession"
```

---

### Task 6: run() method — main message loop

**Files:**
- Modify: `corvus/gateway/chat_session.py`

**Step 1: Write the failing test**

```python
class TestChatSessionRun:
    def test_run_method_exists_and_is_async(self) -> None:
        import inspect
        from corvus.gateway.chat_session import ChatSession
        assert hasattr(ChatSession, "run")
        assert inspect.iscoroutinefunction(ChatSession.run)
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py::TestChatSessionRun -v`
Expected: FAIL

**Step 3: Write implementation**

Add `run()` to `ChatSession`. This is the main message loop (lines 309-1218 from chat.py), but now using `self.*` and `TurnContext`:

```python
    async def run(
        self,
        *,
        started_at: datetime,
        resumed_session: dict | None = None,
    ) -> None:
        """Main WebSocket message loop — processes user messages and dispatches agent runs."""
        from corvus.gateway.chat_engine import resolve_chat_dispatch, resolve_default_agent
        from corvus.gateway.dispatch_metrics import summarize_dispatch_runs
        from corvus.gateway.dispatch_runtime import execute_dispatch_runs
        from corvus.gateway.options import any_llm_configured

        enabled_agents = [agent for agent in self.runtime.agents_hub.list_agents() if agent.enabled]
        await self.send({
            "type": "init",
            "models": [m.to_dict() for m in self.runtime.model_router.list_available_models()],
            "default_model": ui_default_model(self.runtime),
            "agents": [
                {"id": agent.name, "label": agent.name.title(),
                 "description": agent.description, "isDefault": agent.name == "general"}
                for agent in enabled_agents
            ],
            "default_agent": resolve_default_agent(self.runtime),
            "session_id": self.session_id,
            "session_name": (resumed_session or {}).get("summary") or "Huginn",
        })

        if not any_llm_configured():
            logger.warning("No LLM backend configured; running in degraded mode")
            await self._degraded_message_loop()
            return

        while True:
            data = await self.websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await self.send({"type": "error", "message": "Invalid JSON"})
                continue

            if msg.get("type") == "interrupt":
                logger.info("User interrupted session %s", self.session_id)
                await self.runtime.emitter.emit(
                    "session_interrupt", user=self.user, session_id=self.session_id,
                )
                continue

            if msg.get("type") == "ping":
                await self.send({"type": "pong"})
                continue

            if msg.get("type") == "confirm_response":
                call_id = msg.get("tool_call_id")
                approved = msg.get("approved", False)
                await self.send(
                    {"type": "confirm_response", "tool_call_id": call_id, "approved": bool(approved)},
                    persist=True,
                )
                continue

            user_message = msg.get("message", "")
            user_model_raw = msg.get("model")
            user_model = (
                str(user_model_raw).strip()
                if isinstance(user_model_raw, str) and user_model_raw.strip()
                else None
            )
            requested_agent = msg.get("target_agent")
            requested_agents = msg.get("target_agents")
            dispatch_mode_raw = msg.get("dispatch_mode")
            requires_tools = bool(msg.get("requires_tools", False))

            if not user_message:
                continue

            turn_id = str(uuid.uuid4())
            dispatch_id = str(uuid.uuid4())
            self.current_turn_id = turn_id

            dispatch_resolution, dispatch_error = await resolve_chat_dispatch(
                runtime=self.runtime, user_message=user_message,
                requested_agent=requested_agent, requested_agents=requested_agents,
                requested_model=user_model, dispatch_mode_raw=dispatch_mode_raw,
            )

            if dispatch_error:
                await self.send({
                    "type": "error", "error": dispatch_error.error,
                    "message": dispatch_error.message,
                })
                self.current_turn_id = None
                continue

            assert dispatch_resolution is not None
            run_requests = dispatch_resolution.run_requests
            target_agents = dispatch_resolution.target_agents
            dispatch_mode = dispatch_resolution.dispatch_mode
            dispatch_plan = dispatch_resolution.dispatch_plan

            dispatch_interrupted = asyncio.Event()
            turn = TurnContext(
                dispatch_id=dispatch_id,
                turn_id=turn_id,
                dispatch_interrupted=dispatch_interrupted,
                user_model=user_model,
                requires_tools=requires_tools,
            )
            self._current_turn = turn

            try:
                self.runtime.session_mgr.create_dispatch(
                    dispatch_id, session_id=self.session_id, turn_id=turn_id,
                    user=self.user, prompt=user_message, dispatch_mode=dispatch_mode,
                    target_agents=target_agents, status="routing",
                )
            except Exception:
                logger.exception("Failed to persist dispatch row dispatch_id=%s", dispatch_id)

            await self.send(
                {"type": "dispatch_start", "dispatch_id": dispatch_id,
                 "session_id": self.session_id, "turn_id": turn_id,
                 "dispatch_mode": dispatch_mode, "target_agents": target_agents,
                 "message": _preview_summary(user_message, limit=140)},
                persist=True, dispatch_id=dispatch_id, turn_id=turn_id,
            )
            await self.send(
                {"type": "dispatch_plan", "dispatch_id": dispatch_id,
                 "session_id": self.session_id, "turn_id": turn_id,
                 **dispatch_plan.to_payload()},
                persist=True, dispatch_id=dispatch_id, turn_id=turn_id,
            )
            await self.runtime.emitter.emit(
                "dispatch_plan_resolved", dispatch_id=dispatch_id,
                session_id=self.session_id, turn_id=turn_id,
                task_type=dispatch_plan.task_type, decomposed=dispatch_plan.decomposed,
                strategy=dispatch_plan.strategy, route_count=len(run_requests),
                target_agents=target_agents,
            )

            self.transcript.messages.append({"role": "user", "content": user_message})
            self.runtime.session_mgr.add_message(
                session_id=self.session_id, role="user", content=user_message,
                agent=run_requests[0].agent if len(run_requests) == 1 else "general",
                model=user_model,
            )
            self.runtime.dispatch_controls.register(
                dispatch_id=dispatch_id, session_id=self.session_id,
                user=self.user, turn_id=turn_id, interrupt_event=dispatch_interrupted,
            )

            control_listener_task: asyncio.Task[None] | None = None
            try:
                control_listener_task = asyncio.create_task(self.dispatch_control_listener())
                run_results = await execute_dispatch_runs(
                    dispatch_mode=dispatch_mode, run_requests=run_requests,
                    max_parallel_agent_runs=MAX_PARALLEL_AGENT_RUNS,
                    execute_run=self.execute_agent_run,
                    logger=logger, dispatch_interrupted=dispatch_interrupted,
                )

                summary = summarize_dispatch_runs(
                    run_results, interrupted=dispatch_interrupted.is_set(),
                )
                self.runtime.session_mgr.update_dispatch(
                    dispatch_id, status=summary.status, error=summary.error,
                    completed_at=datetime.now(UTC),
                )

                await self.send(
                    {"type": "dispatch_complete", "dispatch_id": dispatch_id,
                     "session_id": self.session_id, "turn_id": turn_id,
                     "status": summary.status, "task_type": dispatch_plan.task_type,
                     "decomposed": dispatch_plan.decomposed, "strategy": dispatch_plan.strategy,
                     "target_agents": target_agents, "total_runs": summary.total_runs,
                     "success_count": summary.success_count, "error_count": summary.error_count,
                     "interrupted_count": summary.interrupted_count,
                     "cost_usd": summary.cost_usd, "max_parallel": MAX_PARALLEL_AGENT_RUNS},
                    persist=True, dispatch_id=dispatch_id, turn_id=turn_id,
                )
                await self.runtime.emitter.emit(
                    "dispatch_completed", dispatch_id=dispatch_id,
                    session_id=self.session_id, turn_id=turn_id,
                    status=summary.status, task_type=dispatch_plan.task_type,
                    decomposed=dispatch_plan.decomposed, strategy=dispatch_plan.strategy,
                    total_runs=summary.total_runs, success_count=summary.success_count,
                    error_count=summary.error_count, interrupted_count=summary.interrupted_count,
                    cost_usd=summary.cost_usd, tokens_used=summary.tokens_used,
                )
                await self.send(
                    {"type": "done", "session_id": self.session_id,
                     "cost_usd": summary.cost_usd, "tokens_used": summary.tokens_used,
                     "context_limit": summary.max_context_limit,
                     "context_pct": summary.max_context_pct},
                )
            except Exception:
                logger.exception("Dispatch failed dispatch_id=%s", dispatch_id)
                self.runtime.session_mgr.update_dispatch(
                    dispatch_id, status="error", error="dispatch_execution_error",
                    completed_at=datetime.now(UTC),
                )
                await self.send({"type": "error", "message": "Internal error: dispatch_execution_error"})
            finally:
                if control_listener_task is not None:
                    if not control_listener_task.done():
                        control_listener_task.cancel()
                    try:
                        await control_listener_task
                    except asyncio.CancelledError:
                        pass
                    except WebSocketDisconnect:
                        raise
                    except Exception:
                        logger.exception("Dispatch control listener failed")
                self.runtime.dispatch_controls.unregister(dispatch_id)
                self._current_turn = None
                self.current_turn_id = None

    async def _degraded_message_loop(self) -> None:
        """Run heartbeat/error loop when no backend is configured."""
        assert self.websocket is not None
        while True:
            data = await self.websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await self.send({"type": "error", "message": "Invalid JSON"})
                continue
            if msg.get("type") == "ping":
                await self.send({"type": "pong"})
                continue
            if msg.get("message"):
                await self.send({
                    "type": "error", "error": "no_llm_configured",
                    "message": "No LLM backend configured. Run 'mise run setup' to add one.",
                })
                continue
```

Add to imports at top:

```python
from fastapi import WebSocketDisconnect

from corvus.config import MAX_PARALLEL_AGENT_RUNS
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/gateway/test_chat_session.py -v`
Expected: PASS (9 tests)

**Step 5: Commit**

```bash
git add corvus/gateway/chat_session.py tests/gateway/test_chat_session.py
git commit -m "feat: add run() message loop to ChatSession — main orchestration method"
```

---

### Task 7: Rewrite chat.py to use ChatSession

**Files:**
- Rewrite: `corvus/api/chat.py`
- Verify: all existing tests still pass

**Step 1: Run existing test suite to establish baseline**

Run: `uv run python -m pytest tests/gateway/ -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_baseline_before_chat_rewrite_results.log`
Expected: All tests pass (capture exact count)

**Step 2: Rewrite chat.py**

Replace the 1,256-line file with ~80 lines:

```python
"""WebSocket chat endpoint — thin router that delegates to ChatSession."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from corvus.config import ALLOWED_USERS
from corvus.gateway.chat_session import ChatSession
from corvus.gateway.runtime import GatewayRuntime
from corvus.session import extract_session_memories

logger = logging.getLogger("corvus-gateway")

router = APIRouter(tags=["chat"])

_runtime: GatewayRuntime | None = None


def configure(runtime: GatewayRuntime) -> None:
    """Wire router to the active gateway runtime."""
    if not isinstance(runtime, GatewayRuntime):
        raise TypeError(f"Expected GatewayRuntime, got {type(runtime).__name__}")
    global _runtime
    _runtime = runtime


def _require_runtime() -> GatewayRuntime:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Gateway runtime not initialized")
    return _runtime


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for persistent chat sessions."""
    runtime = _require_runtime()

    # Auth BEFORE accept — reject unauthorized connections at protocol level.
    user = websocket.headers.get("X-Remote-User") or websocket.headers.get("Remote-User")
    if not user:
        client_host = websocket.client.host if websocket.client else None
        if client_host in ("127.0.0.1", "::1", "localhost"):
            user = ALLOWED_USERS[0]
            logger.debug("Local dev WebSocket: defaulting user to %s", user)
    if not user or user not in ALLOWED_USERS:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    runtime.active_connections.add(websocket)

    requested_session_id = websocket.query_params.get("session_id")
    resumed = False
    resumed_session: dict | None = None
    if requested_session_id:
        resumed_session = runtime.session_mgr.get(requested_session_id)
        if resumed_session and resumed_session.get("user") == user:
            session_id = requested_session_id
            resumed = True
        else:
            requested_session_id = None
            resumed_session = None

    if resumed:
        started_at = datetime.now(UTC)
        logger.info("Resumed chat session for user=%s session_id=%s", user, session_id)
    else:
        session_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        logger.info("Chat session started for user=%s session_id=%s", user, session_id)
        runtime.session_mgr.start(session_id, user=user, started_at=started_at)

    await runtime.emitter.emit("session_start", user=user, session_id=session_id)

    session = ChatSession(
        runtime=runtime,
        websocket=websocket,
        user=user,
        session_id=session_id,
    )

    try:
        await session.run(started_at=started_at, resumed_session=resumed_session)
    except WebSocketDisconnect:
        runtime.active_connections.discard(websocket)
        logger.info("Chat session ended for user=%s session_id=%s", user, session_id)
        await runtime.emitter.emit(
            "session_end", user=user, session_id=session_id,
            message_count=session.transcript.message_count(),
            duration_seconds=(datetime.now(UTC) - started_at).total_seconds(),
        )
        try:
            runtime.session_mgr.end(
                session_id=session_id, ended_at=datetime.now(UTC),
                message_count=session.transcript.message_count(),
                tool_count=session.transcript.tool_count,
                agents_used=list(session.transcript.agents_used),
            )
        except Exception:
            logger.exception("Failed to end session %s", session_id)
        try:
            memories = await extract_session_memories(
                session.transcript, runtime.memory_hub,
                agent_name=session.transcript.primary_agent(),
            )
            if memories:
                logger.info("Extracted %d memories from session for user=%s", len(memories), user)
        except Exception:
            logger.exception("Session memory extraction failed for user=%s", user)
    except Exception:
        runtime.active_connections.discard(websocket)
        logger.exception("Error in chat session")
        await websocket.close(code=1011, reason="Internal error")
```

**Step 3: Update `corvus/gateway/__init__.py` to export `ChatSession`**

Add to imports and `__all__`:

```python
from corvus.gateway.chat_session import ChatSession, TurnContext
```

Add `"ChatSession"` and `"TurnContext"` to `__all__`.

**Step 4: Run the full gateway test suite**

Run: `uv run python -m pytest tests/gateway/ -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_after_chat_rewrite_results.log`
Expected: Same pass count as baseline. Zero regressions.

**Step 5: Verify frontend contract tests specifically**

Run: `uv run python -m pytest tests/gateway/test_frontend_backend_contracts.py tests/gateway/test_chat_no_llm.py tests/gateway/test_ws_protocol.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add corvus/api/chat.py corvus/gateway/chat_session.py corvus/gateway/__init__.py
git commit -m "refactor: rewrite chat.py to use ChatSession — 1256 lines → 80 lines + class"
```

---

### Task 8: Remove B023 suppression and verify lint

**Files:**
- Verify: `corvus/gateway/chat_session.py` has no ruff B023 issues
- Verify: `corvus/api/chat.py` no longer needs `# ruff: noqa: B023`

**Step 1: Confirm the B023 suppression is no longer in chat.py**

The rewritten `chat.py` from Task 7 should not include `# ruff: noqa: B023`. Verify:

Run: `grep -n 'B023' corvus/api/chat.py` — should find nothing.

**Step 2: Run ruff on the new files**

Run: `uv run ruff check corvus/api/chat.py corvus/gateway/chat_session.py`
Expected: No errors (or only pre-existing unrelated issues)

**Step 3: Run full gateway tests one final time**

Run: `uv run python -m pytest tests/gateway/ -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_final_validation_results.log`
Expected: All pass

**Step 4: Commit if any cleanup was needed**

```bash
git add -A
git commit -m "chore: remove B023 suppression — closure soup eliminated by ChatSession class"
```

---

## Validation Checklist

After all tasks complete, verify:

- [ ] `mise run test:gateway` passes with same count as before
- [ ] `mise run lint` shows no new issues from this change
- [ ] `corvus/api/chat.py` is ~80 lines
- [ ] `corvus/gateway/chat_session.py` contains `ChatSession` class with `TurnContext`
- [ ] `# ruff: noqa: B023` no longer exists in `corvus/api/chat.py`
- [ ] WS protocol contract tests pass unchanged
- [ ] `test_chat_no_llm.py` passes unchanged
- [ ] No lazy imports introduced
- [ ] No relative imports introduced
- [ ] `background_dispatch.py` is untouched
