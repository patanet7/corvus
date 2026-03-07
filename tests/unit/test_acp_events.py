"""Behavioral tests for ACP event translator — no mocks."""

from corvus.acp.events import translate_acp_update

_BASE_KWARGS: dict = {
    "run_id": "run_1",
    "session_id": "sess_1",
    "turn_id": "turn_1",
    "dispatch_id": "disp_1",
    "agent": "homelab",
    "model": "codex-mini",
    "chunk_index": 0,
    "route_payload": {
        "task_type": "code",
        "subtask_id": "fix-auth",
        "skill": None,
        "instruction": "fix auth",
        "route_index": 0,
    },
}


def test_agent_message_chunk() -> None:
    update = {"kind": "agent_message_chunk", "content": "Hello world"}
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 2
    assert events[0]["type"] == "run_output_chunk"
    assert events[0]["content"] == "Hello world"
    assert events[0]["chunk_index"] == 0
    assert events[0]["final"] is False
    assert events[0]["run_id"] == "run_1"
    assert events[0]["session_id"] == "sess_1"
    assert events[0]["agent"] == "homelab"
    # route_payload fields spread into event
    assert events[0]["task_type"] == "code"

    assert events[1]["type"] == "text"
    assert events[1]["content"] == "Hello world"
    assert events[1]["run_id"] == "run_1"


def test_agent_thought_chunk() -> None:
    update = {"kind": "agent_thought_chunk", "content": "Let me think..."}
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "thinking"
    assert events[0]["content"] == "Let me think..."
    assert events[0]["run_id"] == "run_1"
    assert events[0]["agent"] == "homelab"


def test_tool_call() -> None:
    update = {
        "kind": "tool_call",
        "tool_name": "bash",
        "tool_call_id": "tc_42",
        "description": "Run ls -la",
        "status": "running",
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "tool_use"
    assert events[0]["tool_name"] == "bash"
    assert events[0]["tool_call_id"] == "tc_42"
    assert events[0]["description"] == "Run ls -la"
    assert events[0]["status"] == "running"
    assert events[0]["run_id"] == "run_1"


def test_tool_call_update() -> None:
    update = {
        "kind": "tool_call_update",
        "tool_call_id": "tc_42",
        "status": "completed",
        "content": "total 24\ndrwxr-xr-x  5 user staff",
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "tool_result"
    assert events[0]["tool_call_id"] == "tc_42"
    assert events[0]["status"] == "completed"
    assert events[0]["content"] == "total 24\ndrwxr-xr-x  5 user staff"
    assert events[0]["run_id"] == "run_1"


def test_unknown_kind_ignored() -> None:
    update = {"kind": "some_future_event", "data": {"foo": "bar"}}
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert events == []
