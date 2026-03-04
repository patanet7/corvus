"""Behavioral tests for ChatSession class and TurnContext.

All tests are behavioral: real SQLite databases, real objects.
NO mocks, NO monkeypatch, NO @patch.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from corvus.gateway.chat_session import (
    _PERSISTED_RUN_EVENT_TYPES,
    _PERSISTED_SESSION_EVENT_TYPES,
    _TRACE_EVENT_TYPES,
    ChatSession,
    TurnContext,
    _optional_str,
    _preview_summary,
    _trace_source_app,
    _trace_summary,
)
from corvus.gateway.task_planner import TaskRoute
from corvus.gateway.trace_hub import TraceHub
from corvus.session_manager import SessionManager

SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed",
)


# ---------------------------------------------------------------------------
# Lightweight runtime helper for ChatSession behavioral tests.
#
# build_runtime() pulls in the full gateway stack (agent registry, model router,
# client pool, etc.) and shares a single SQLite DB across the process, which
# causes "database is locked" errors when tests run in parallel. Instead we
# construct only the components ChatSession actually touches in these tests:
# session_mgr and trace_hub, backed by a fresh per-test temp database.
# ---------------------------------------------------------------------------


class _MinimalRuntime:
    """Behaviorally sufficient stand-in for GatewayRuntime.

    NOT a mock — every attribute is a real, fully functional object backed
    by a real SQLite database. ChatSession only accesses ``session_mgr``
    and ``trace_hub`` in the methods under test (send, _persist_*, _publish_trace).
    """

    def __init__(self, db_path: Path) -> None:
        self.session_mgr = SessionManager(db_path=db_path)
        self.trace_hub = TraceHub()


def _make_session(tmp_path: Path, session_id: str | None = None) -> tuple[_MinimalRuntime, ChatSession]:
    """Create a ChatSession with an isolated SQLite DB for behavioral tests."""
    sid = session_id or f"sess-{uuid4().hex[:8]}"
    runtime = _MinimalRuntime(db_path=tmp_path / f"{sid}.sqlite")
    runtime.session_mgr.start(sid, user="testuser")
    session = ChatSession(
        runtime=runtime,  # type: ignore[arg-type]
        websocket=None,
        user="testuser",
        session_id=sid,
    )
    return runtime, session


# ---------------------------------------------------------------------------
# TurnContext
# ---------------------------------------------------------------------------


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

    def test_turn_context_uses_slots(self) -> None:
        """TurnContext dataclass uses slots=True for memory efficiency."""
        assert hasattr(TurnContext, "__slots__")

    def test_turn_context_interrupt_event_is_independent(self) -> None:
        """Each TurnContext gets its own interrupt event instance."""
        e1 = asyncio.Event()
        e2 = asyncio.Event()
        ctx1 = TurnContext(
            dispatch_id="d-1",
            turn_id="t-1",
            dispatch_interrupted=e1,
            user_model=None,
            requires_tools=False,
        )
        ctx2 = TurnContext(
            dispatch_id="d-2",
            turn_id="t-2",
            dispatch_interrupted=e2,
            user_model=None,
            requires_tools=False,
        )
        e1.set()
        assert ctx1.dispatch_interrupted.is_set()
        assert not ctx2.dispatch_interrupted.is_set()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestPreviewSummary:
    def test_short_text_unchanged(self) -> None:
        assert _preview_summary("Hello world") == "Hello world"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        long_text = "A" * 200
        result = _preview_summary(long_text, limit=50)
        assert len(result) == 50
        assert result.endswith("\u2026")

    def test_whitespace_collapsed(self) -> None:
        assert _preview_summary("foo   bar\n  baz") == "foo bar baz"


class TestOptionalStr:
    def test_returns_none_for_non_string(self) -> None:
        assert _optional_str(42) is None
        assert _optional_str(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _optional_str("") is None
        assert _optional_str("   ") is None

    def test_returns_stripped_string(self) -> None:
        assert _optional_str("  hello  ") == "hello"


class TestTraceSourceApp:
    def test_agent_from_payload(self) -> None:
        assert _trace_source_app("run_start", {"agent": "homelab"}) == "homelab"

    def test_dispatch_event_returns_router(self) -> None:
        assert _trace_source_app("dispatch_start", {}) == "router"
        assert _trace_source_app("dispatch_plan", {}) == "router"
        assert _trace_source_app("dispatch_complete", {}) == "router"
        assert _trace_source_app("routing", {}) == "router"

    def test_fallback_returns_gateway(self) -> None:
        assert _trace_source_app("run_start", {}) == "gateway"


class TestTraceSummary:
    def test_summary_from_payload(self) -> None:
        result = _trace_summary("run_start", {"summary": "Starting agent"})
        assert result == "Starting agent"

    def test_output_chunk_content(self) -> None:
        result = _trace_summary("run_output_chunk", {"content": "Some response text"})
        assert result == "Some response text"

    def test_output_chunk_final_marker(self) -> None:
        result = _trace_summary("run_output_chunk", {"final": True})
        assert result == "Final output marker"

    def test_tool_start(self) -> None:
        result = _trace_summary("tool_start", {"tool": "Bash"})
        assert result == "Tool start: Bash"

    def test_tool_result(self) -> None:
        result = _trace_summary("tool_result", {})
        assert result == "Tool result (success)"

    def test_confirm_request(self) -> None:
        result = _trace_summary("confirm_request", {"tool": "Write"})
        assert result == "Confirm request: Write"

    def test_tool_permission_decision(self) -> None:
        result = _trace_summary(
            "tool_permission_decision",
            {"tool": "Bash", "state": "allow"},
        )
        assert result == "Permission allow: Bash"

    def test_message_fallback(self) -> None:
        result = _trace_summary("error", {"message": "Something went wrong"})
        assert result == "Something went wrong"

    def test_returns_none_for_unknown(self) -> None:
        assert _trace_summary("unknown_event", {}) is None


# ---------------------------------------------------------------------------
# Event type sets
# ---------------------------------------------------------------------------


class TestEventTypeSets:
    def test_persisted_session_event_types_is_superset_of_run_events(self) -> None:
        """All persisted run event types should also be in session event types."""
        assert _PERSISTED_RUN_EVENT_TYPES.issubset(_PERSISTED_SESSION_EVENT_TYPES)

    def test_trace_event_types_includes_session_events(self) -> None:
        assert _PERSISTED_SESSION_EVENT_TYPES.issubset(_TRACE_EVENT_TYPES)

    def test_trace_event_types_includes_routing_and_error(self) -> None:
        assert "routing" in _TRACE_EVENT_TYPES
        assert "agent_status" in _TRACE_EVENT_TYPES
        assert "error" in _TRACE_EVENT_TYPES

    def test_expected_session_event_count(self) -> None:
        """Guard against accidental changes to the event type sets."""
        assert len(_PERSISTED_SESSION_EVENT_TYPES) == 16
        assert len(_PERSISTED_RUN_EVENT_TYPES) == 9


# ---------------------------------------------------------------------------
# ChatSession construction + attributes
# ---------------------------------------------------------------------------


class TestChatSessionInit:
    def test_chat_session_attributes(self, tmp_path) -> None:
        _, session = _make_session(tmp_path, "test-init-session")
        assert session.user == "testuser"
        assert session.session_id == "test-init-session"
        assert session.runtime is not None
        assert session.current_turn_id is None
        assert session._current_turn is None

    def test_chat_session_transcript_initialized(self, tmp_path) -> None:
        _, session = _make_session(tmp_path, "test-transcript-init")
        assert session.transcript.user == "testuser"
        assert session.transcript.session_id == "test-transcript-init"
        assert session.transcript.messages == []

    def test_chat_session_send_lock_is_asyncio_lock(self, tmp_path) -> None:
        _, session = _make_session(tmp_path)
        assert isinstance(session.send_lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# ChatSession._persist_session_event
# ---------------------------------------------------------------------------


class TestChatSessionPersistSessionEvent:
    def test_persist_session_event_writes_to_session_mgr(self, tmp_path) -> None:
        """Verify _persist_session_event writes to the real session store."""
        runtime, session = _make_session(tmp_path, "test-persist-session")
        session.current_turn_id = "turn-1"
        session._persist_session_event(
            event_type="dispatch_start",
            payload={"type": "dispatch_start", "dispatch_id": "d-1"},
            turn_id="turn-1",
        )
        events = runtime.session_mgr.list_events("test-persist-session")
        assert len(events) >= 1
        found = [e for e in events if e["event_type"] == "dispatch_start"]
        assert len(found) == 1

    def test_persist_session_event_uses_current_turn_id_as_fallback(self, tmp_path) -> None:
        """When turn_id is None, falls back to session.current_turn_id."""
        runtime, session = _make_session(tmp_path, "test-persist-fallback")
        session.current_turn_id = "turn-fallback"
        session._persist_session_event(
            event_type="run_start",
            payload={"type": "run_start"},
            turn_id=None,
        )
        events = runtime.session_mgr.list_events("test-persist-fallback")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# ChatSession._base_payload
# ---------------------------------------------------------------------------


class TestBasePayload:
    def test_base_payload_includes_required_fields(self) -> None:
        ctx = TurnContext(
            dispatch_id="d-1",
            turn_id="t-1",
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=False,
        )
        route_payload = {
            "task_type": "chat",
            "subtask_id": None,
            "skill": None,
            "instruction": None,
            "route_index": 0,
        }
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
        assert result["route_index"] == 0

    def test_base_payload_merges_route_payload(self) -> None:
        ctx = TurnContext(
            dispatch_id="d-2",
            turn_id="t-2",
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=False,
        )
        route_payload = {
            "task_type": "analysis",
            "subtask_id": "sub-1",
            "skill": "code_review",
            "instruction": "Review PR",
            "route_index": 2,
        }
        result = ChatSession._base_payload(
            turn=ctx,
            run_id="r-2",
            task_id="task-r2",
            agent="work",
            route_payload=route_payload,
            session_id="s-2",
        )
        assert result["subtask_id"] == "sub-1"
        assert result["skill"] == "code_review"
        assert result["instruction"] == "Review PR"
        assert result["route_index"] == 2

    def test_base_payload_is_static_method(self) -> None:
        assert isinstance(
            inspect.getattr_static(ChatSession, "_base_payload"),
            staticmethod,
        )


# ---------------------------------------------------------------------------
# ChatSession._emit_phase and _emit_run_failure -- existence and signatures
# ---------------------------------------------------------------------------


class TestEmitPhaseAndFailureSignatures:
    def test_emit_phase_is_async_method(self) -> None:
        assert inspect.iscoroutinefunction(ChatSession._emit_phase)

    def test_emit_phase_signature(self) -> None:
        sig = inspect.signature(ChatSession._emit_phase)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "turn" in params
        assert "run_id" in params
        assert "task_id" in params
        assert "agent" in params
        assert "route_payload" in params
        assert "phase" in params
        assert "summary" in params

    def test_emit_run_failure_is_async_method(self) -> None:
        assert inspect.iscoroutinefunction(ChatSession._emit_run_failure)

    def test_emit_run_failure_signature(self) -> None:
        sig = inspect.signature(ChatSession._emit_run_failure)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "turn" in params
        assert "run_id" in params
        assert "task_id" in params
        assert "agent" in params
        assert "route_payload" in params
        assert "error_type" in params
        assert "summary" in params
        assert "context_limit" in params

    def test_emit_run_failure_returns_dict(self) -> None:
        """Return type annotation should indicate dict."""
        sig = inspect.signature(ChatSession._emit_run_failure)
        # With `from __future__ import annotations`, return_annotation is a string
        assert sig.return_annotation in (dict, "dict")


# ---------------------------------------------------------------------------
# ChatSession.send -- decomposed orchestrator
# ---------------------------------------------------------------------------


class TestChatSessionSendSignature:
    def test_send_is_async_method(self) -> None:
        assert inspect.iscoroutinefunction(ChatSession.send)

    def test_send_signature(self) -> None:
        sig = inspect.signature(ChatSession.send)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "payload" in params
        assert "persist" in params
        assert "run_id" in params
        assert "dispatch_id" in params
        assert "turn_id" in params

    def test_ws_send_is_async_method(self) -> None:
        assert inspect.iscoroutinefunction(ChatSession._ws_send)

    def test_persist_session_event_is_sync(self) -> None:
        """_persist_session_event is synchronous (SQLite writes are sync)."""
        assert not inspect.iscoroutinefunction(ChatSession._persist_session_event)

    def test_persist_run_event_is_sync(self) -> None:
        assert not inspect.iscoroutinefunction(ChatSession._persist_run_event)

    def test_publish_trace_is_async(self) -> None:
        assert inspect.iscoroutinefunction(ChatSession._publish_trace)


# ---------------------------------------------------------------------------
# ChatSession.send -- behavioral test with no WS (each test gets its own DB)
# ---------------------------------------------------------------------------


class TestChatSessionSendBehavior:
    def test_send_persists_session_event(self, tmp_path) -> None:
        runtime, session = _make_session(tmp_path, "test-send-persist")
        session.current_turn_id = "turn-1"
        payload = {"type": "dispatch_start", "dispatch_id": "d-send-1"}
        asyncio.run(session.send(payload, persist=True, turn_id="turn-1"))
        events = runtime.session_mgr.list_events("test-send-persist")
        found = [e for e in events if e["event_type"] == "dispatch_start"]
        assert len(found) == 1

    def test_send_does_not_persist_when_persist_false(self, tmp_path) -> None:
        runtime, session = _make_session(tmp_path, "test-send-no-persist")
        payload = {"type": "dispatch_start", "dispatch_id": "d-no-persist"}
        asyncio.run(session.send(payload, persist=False))
        events = runtime.session_mgr.list_events("test-send-no-persist")
        found = [e for e in events if e["event_type"] == "dispatch_start"]
        assert len(found) == 0

    def test_send_persists_run_event_when_ids_provided(self, tmp_path) -> None:
        sid = "test-send-run-evt"
        runtime, session = _make_session(tmp_path, sid)
        session.current_turn_id = "turn-1"
        runtime.session_mgr.create_dispatch(
            "d-run-1",
            session_id=sid,
            user="testuser",
            prompt="test",
            dispatch_mode="direct",
            target_agents=["general"],
            turn_id="turn-1",
        )
        runtime.session_mgr.start_agent_run(
            "r-run-1",
            dispatch_id="d-run-1",
            session_id=sid,
            agent="general",
            turn_id="turn-1",
        )
        payload = {"type": "run_start", "dispatch_id": "d-run-1", "run_id": "r-run-1"}
        asyncio.run(
            session.send(
                payload,
                persist=True,
                run_id="r-run-1",
                dispatch_id="d-run-1",
                turn_id="turn-1",
            )
        )
        run_events = runtime.session_mgr.list_run_events("r-run-1")
        assert len(run_events) >= 1

    def test_send_persists_tool_permission_decision_events(self, tmp_path) -> None:
        sid = "test-send-permission-event"
        runtime, session = _make_session(tmp_path, sid)
        session.current_turn_id = "turn-perm-1"
        runtime.session_mgr.create_dispatch(
            "d-perm-1",
            session_id=sid,
            user="testuser",
            prompt="test permission event",
            dispatch_mode="direct",
            target_agents=["general"],
            turn_id="turn-perm-1",
        )
        runtime.session_mgr.start_agent_run(
            "r-perm-1",
            dispatch_id="d-perm-1",
            session_id=sid,
            agent="general",
            turn_id="turn-perm-1",
        )
        payload = {
            "type": "tool_permission_decision",
            "dispatch_id": "d-perm-1",
            "run_id": "r-perm-1",
            "task_id": "task-r-perm-1",
            "session_id": sid,
            "turn_id": "turn-perm-1",
            "agent": "general",
            "tool": "Bash",
            "allowed": True,
            "state": "allow",
            "scope": "builtin",
            "reason": "Allowed by builtin tool policy.",
        }
        asyncio.run(
            session.send(
                payload,
                persist=True,
                run_id="r-perm-1",
                dispatch_id="d-perm-1",
                turn_id="turn-perm-1",
            )
        )
        session_events = runtime.session_mgr.list_events(sid)
        assert any(event["event_type"] == "tool_permission_decision" for event in session_events)
        run_events = runtime.session_mgr.list_run_events("r-perm-1")
        assert any(event["event_type"] == "tool_permission_decision" for event in run_events)

    def test_send_no_ws_does_not_raise(self, tmp_path) -> None:
        """When websocket is None, _ws_send is a no-op (does not raise)."""
        _, session = _make_session(tmp_path)
        asyncio.run(session.send({"type": "pong"}))

    def test_send_persists_trace_event_for_persisted_types(self, tmp_path) -> None:
        """Trace events are persisted for event types in _TRACE_EVENT_TYPES."""
        sid = "test-send-trace"
        runtime, session = _make_session(tmp_path, sid)
        session.current_turn_id = "turn-1"
        # Use dispatch_id=None to avoid FK constraint (no dispatch row needed)
        payload = {"type": "dispatch_start"}
        asyncio.run(
            session.send(
                payload,
                persist=True,
                turn_id="turn-1",
            )
        )
        traces = runtime.session_mgr.list_trace_events(session_ids=[sid])
        assert len(traces) >= 1

    def test_send_does_not_trace_non_trace_types(self, tmp_path) -> None:
        """Event types NOT in _TRACE_EVENT_TYPES should not create trace rows."""
        sid = "test-send-no-trace"
        runtime, session = _make_session(tmp_path, sid)
        session.current_turn_id = "turn-1"
        payload = {"type": "text", "content": "hello"}
        asyncio.run(session.send(payload, persist=False))
        traces = runtime.session_mgr.list_trace_events(session_ids=[sid])
        assert len(traces) == 0


# ---------------------------------------------------------------------------
# ChatSession._emit_run_failure -- behavioral test
# ---------------------------------------------------------------------------


class TestEmitRunFailureBehavior:
    def test_emit_run_failure_persists_events_and_updates_run(self, tmp_path) -> None:
        """_emit_run_failure writes run_complete, task_complete, and updates the run record."""
        sid = "test-failure"
        runtime, session = _make_session(tmp_path, sid)
        session.current_turn_id = "turn-fail"

        # Set up dispatch + run
        runtime.session_mgr.create_dispatch(
            "d-fail",
            session_id=sid,
            user="testuser",
            prompt="fail test",
            dispatch_mode="direct",
            target_agents=["general"],
            turn_id="turn-fail",
        )
        runtime.session_mgr.start_agent_run(
            "r-fail",
            dispatch_id="d-fail",
            session_id=sid,
            agent="general",
            turn_id="turn-fail",
        )

        turn = TurnContext(
            dispatch_id="d-fail",
            turn_id="turn-fail",
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=False,
        )
        route_payload = {
            "task_type": None,
            "subtask_id": None,
            "skill": None,
            "instruction": None,
            "route_index": 0,
        }

        result = asyncio.run(
            session._emit_run_failure(
                turn,
                run_id="r-fail",
                task_id="task-fail",
                agent="general",
                route_payload=route_payload,
                error_type="test_error",
                summary="Test failure summary",
                context_limit=200000,
            )
        )

        # Verify return value shape
        assert result["result"] == "error"
        assert result["cost_usd"] == 0.0
        assert result["tokens_used"] == 0
        assert result["context_pct"] == 0.0

        # Verify run was updated in DB
        run = runtime.session_mgr.get_run("r-fail")
        assert run is not None
        assert run["status"] == "error"

        # Verify session events were persisted (run_phase + run_complete + task_complete)
        events = runtime.session_mgr.list_events(sid)
        event_types = [e["event_type"] for e in events]
        assert "run_phase" in event_types
        assert "run_complete" in event_types
        assert "task_complete" in event_types


# ---------------------------------------------------------------------------
# ChatSession._emit_run_interrupted — existence and signature
# ---------------------------------------------------------------------------


class TestEmitRunInterrupted:
    def test_emit_run_interrupted_exists_and_is_async(self) -> None:
        assert hasattr(ChatSession, "_emit_run_interrupted")
        assert inspect.iscoroutinefunction(ChatSession._emit_run_interrupted)

    def test_emit_run_interrupted_signature(self) -> None:
        sig = inspect.signature(ChatSession._emit_run_interrupted)
        params = list(sig.parameters.keys())
        assert "self" in params
        for name in ("turn", "run_id", "task_id", "agent", "route_payload",
                     "summary", "cost_usd", "tokens_used", "context_limit", "context_pct"):
            assert name in params, f"Missing parameter: {name}"
        # All params after turn must be keyword-only
        for name in params[2:]:
            assert sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY

    def test_emit_run_interrupted_returns_dict(self) -> None:
        """Source-level check: method returns a dict with 'interrupted' result."""
        source = Path(__file__).parent.parent.parent / "corvus" / "gateway" / "chat_session.py"
        text = source.read_text()
        assert '"result": "interrupted"' in text


# ---------------------------------------------------------------------------
# ChatSession._execute_dispatch_lifecycle — existence and signature
# ---------------------------------------------------------------------------


class TestExecuteDispatchLifecycle:
    def test_execute_dispatch_lifecycle_exists_and_is_async(self) -> None:
        assert hasattr(ChatSession, "_execute_dispatch_lifecycle")
        assert inspect.iscoroutinefunction(ChatSession._execute_dispatch_lifecycle)

    def test_execute_dispatch_lifecycle_signature(self) -> None:
        sig = inspect.signature(ChatSession._execute_dispatch_lifecycle)
        params = list(sig.parameters.keys())
        assert "self" in params
        for name in ("dispatch_id", "turn_id", "resolution", "user_message",
                     "user_model", "requires_tools"):
            assert name in params, f"Missing parameter: {name}"
        # All params should be keyword-only
        for name in params[1:]:
            assert sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY

    def test_run_delegates_to_execute_dispatch_lifecycle(self) -> None:
        """Source-level check: run() calls _execute_dispatch_lifecycle."""
        source = Path(__file__).parent.parent.parent / "corvus" / "gateway" / "chat_session.py"
        text = source.read_text()
        assert "await self._execute_dispatch_lifecycle(" in text


# ---------------------------------------------------------------------------
# ChatSession.execute_agent_run — existence and protocol conformance
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestChatSessionExecuteAgentRun:
    @pytest.fixture()
    def session(self, tmp_path) -> ChatSession:
        _, session = _make_session(tmp_path, "test-run-session")
        return session

    def test_execute_agent_run_exists_and_is_async(self, session) -> None:
        assert hasattr(session, "execute_agent_run")
        assert inspect.iscoroutinefunction(session.execute_agent_run)

    def test_execute_agent_run_matches_run_executor_protocol(self, session) -> None:
        sig = inspect.signature(session.execute_agent_run)
        params = list(sig.parameters.keys())
        assert "route" in params
        assert "route_index" in params
        ri_param = sig.parameters["route_index"]
        assert ri_param.kind == inspect.Parameter.KEYWORD_ONLY

    def test_execute_agent_run_asserts_active_turn_context(self, session) -> None:
        """Calling execute_agent_run without a TurnContext raises AssertionError."""
        route = TaskRoute(
            agent="general",
            prompt="hello",
            requested_model=None,
        )
        with pytest.raises(AssertionError, match="requires an active TurnContext"):
            asyncio.run(session.execute_agent_run(route, route_index=0))

    def test_route_payload_static_method(self) -> None:
        """_route_payload is a static method that builds route-level fields."""
        assert isinstance(
            inspect.getattr_static(ChatSession, "_route_payload"),
            staticmethod,
        )
        route = TaskRoute(
            agent="homelab",
            prompt="test",
            requested_model=None,
            task_type="automation",
            subtask_id="sub-1",
            skill="docker",
            instruction="restart container",
        )
        result = ChatSession._route_payload(route, route_index=3)
        assert result == {
            "task_type": "automation",
            "subtask_id": "sub-1",
            "skill": "docker",
            "instruction": "restart container",
            "route_index": 3,
        }


# ---------------------------------------------------------------------------
# ChatSession.dispatch_control_listener — existence and signature
# ---------------------------------------------------------------------------


class TestDispatchControlListener:
    def test_dispatch_control_listener_exists_and_is_async(self) -> None:
        assert hasattr(ChatSession, "dispatch_control_listener")
        assert inspect.iscoroutinefunction(ChatSession.dispatch_control_listener)

    def test_dispatch_control_listener_signature(self) -> None:
        sig = inspect.signature(ChatSession.dispatch_control_listener)
        params = list(sig.parameters.keys())
        assert "self" in params
        # Should have no other required parameters
        assert len(params) == 1

    def test_dispatch_control_listener_asserts_active_turn_context(self, tmp_path) -> None:
        """Calling dispatch_control_listener without a TurnContext raises AssertionError."""
        _, session = _make_session(tmp_path)
        with pytest.raises(AssertionError, match="requires an active TurnContext"):
            asyncio.run(session.dispatch_control_listener())

    def test_dispatch_control_listener_asserts_active_websocket(self, tmp_path) -> None:
        """Calling dispatch_control_listener without a WebSocket raises AssertionError."""
        _, session = _make_session(tmp_path)
        # Set a TurnContext but leave websocket as None
        session._current_turn = TurnContext(
            dispatch_id="d-test",
            turn_id="t-test",
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=False,
        )
        with pytest.raises(AssertionError, match="requires an active WebSocket"):
            asyncio.run(session.dispatch_control_listener())


# ---------------------------------------------------------------------------
# ChatSession.run — existence and signature
# ---------------------------------------------------------------------------


class TestChatSessionRun:
    def test_run_method_exists_and_is_async(self) -> None:
        assert hasattr(ChatSession, "run")
        assert inspect.iscoroutinefunction(ChatSession.run)

    def test_run_signature(self) -> None:
        sig = inspect.signature(ChatSession.run)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "started_at" in params
        assert "resumed_session" in params
        # started_at and resumed_session should be keyword-only
        assert sig.parameters["started_at"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["resumed_session"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_run_asserts_active_websocket(self, tmp_path) -> None:
        """Calling run() without a WebSocket raises AssertionError."""
        _, session = _make_session(tmp_path)
        with pytest.raises(AssertionError, match="requires an active WebSocket"):
            asyncio.run(session.run(started_at=datetime.now(UTC)))


# ---------------------------------------------------------------------------
# ChatSession._degraded_message_loop — existence and signature
# ---------------------------------------------------------------------------


class TestDegradedMessageLoop:
    def test_degraded_message_loop_exists(self) -> None:
        assert hasattr(ChatSession, "_degraded_message_loop")
        assert inspect.iscoroutinefunction(ChatSession._degraded_message_loop)

    def test_degraded_message_loop_asserts_active_websocket(self, tmp_path) -> None:
        """Calling _degraded_message_loop without a WebSocket raises AssertionError."""
        _, session = _make_session(tmp_path)
        with pytest.raises(AssertionError, match="requires an active WebSocket"):
            asyncio.run(session._degraded_message_loop())
