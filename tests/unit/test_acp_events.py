"""Behavioral tests for ACP event translator — no mocks.

Tests use the real ACP sessionUpdate format (discriminator field).
"""

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
    update = {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": "Hello world"},
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 2
    assert events[0]["type"] == "run_output_chunk"
    assert events[0]["content"] == "Hello world"
    assert events[0]["chunk_index"] == 0
    assert events[0]["final"] is False
    assert events[0]["run_id"] == "run_1"
    assert events[0]["session_id"] == "sess_1"
    assert events[0]["agent"] == "homelab"
    assert events[0]["task_type"] == "code"

    assert events[1]["type"] == "text"
    assert events[1]["content"] == "Hello world"
    assert events[1]["run_id"] == "run_1"


def test_agent_message_chunk_raw_string_fallback() -> None:
    """ContentBlock can also be a raw string for backwards compat."""
    update = {"sessionUpdate": "agent_message_chunk", "content": "raw text"}
    events = translate_acp_update(update, **_BASE_KWARGS)
    assert events[0]["content"] == "raw text"


def test_agent_thought_chunk() -> None:
    update = {
        "sessionUpdate": "agent_thought_chunk",
        "content": {"type": "text", "text": "Let me think..."},
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "thinking"
    assert events[0]["content"] == "Let me think..."
    assert events[0]["run_id"] == "run_1"
    assert events[0]["agent"] == "homelab"


def test_tool_call() -> None:
    update = {
        "sessionUpdate": "tool_call",
        "toolCallId": "tc_42",
        "title": "Reading configuration file",
        "kind": "read",
        "status": "pending",
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "tool_use"
    assert events[0]["tool_name"] == "Reading configuration file"
    assert events[0]["tool_call_id"] == "tc_42"
    assert events[0]["kind"] == "read"
    assert events[0]["status"] == "pending"
    assert events[0]["run_id"] == "run_1"


def test_tool_call_update() -> None:
    update = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "tc_42",
        "status": "completed",
        "content": [
            {"type": "content", "content": {"type": "text", "text": "Config loaded"}},
        ],
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "tool_result"
    assert events[0]["tool_call_id"] == "tc_42"
    assert events[0]["status"] == "completed"
    assert events[0]["content"] == "Config loaded"
    assert events[0]["run_id"] == "run_1"


def test_plan_update() -> None:
    update = {
        "sessionUpdate": "plan",
        "entries": [
            {"content": "Check syntax", "priority": "high", "status": "completed"},
            {"content": "Review types", "priority": "medium", "status": "in_progress"},
        ],
    }
    events = translate_acp_update(update, **_BASE_KWARGS)

    assert len(events) == 1
    assert events[0]["type"] == "task_progress"
    assert "Check syntax" in events[0]["summary"]
    assert "Review types" in events[0]["summary"]


def test_unknown_update_type_ignored() -> None:
    update = {"sessionUpdate": "some_future_event", "data": {"foo": "bar"}}
    events = translate_acp_update(update, **_BASE_KWARGS)
    assert events == []
