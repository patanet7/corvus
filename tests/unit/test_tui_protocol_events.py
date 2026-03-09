"""Behavioral tests for corvus.tui.protocol.events — parse_event() contract.

Verifies that raw WebSocket dicts are correctly parsed into typed event
dataclasses, preserving all fields and defaulting missing ones.
"""

import pytest

from corvus.tui.protocol.events import (
    ConfirmRequest,
    DispatchStart,
    ErrorEvent,
    ProtocolEvent,
    RunOutputChunk,
    RunPhase,
    ToolStart,
    parse_event,
)


class TestParseDispatchStart:
    """dispatch_start events parse into DispatchStart with all fields."""

    def test_full_payload(self) -> None:
        raw = {
            "type": "dispatch_start",
            "dispatch_id": "d-001",
            "session_id": "s-100",
            "turn_id": "t-50",
            "plan": "route to homelab",
        }
        event = parse_event(raw)
        assert isinstance(event, DispatchStart)
        assert event.type == "dispatch_start"
        assert event.dispatch_id == "d-001"
        assert event.session_id == "s-100"
        assert event.turn_id == "t-50"
        assert event.raw is raw

    def test_missing_optional_fields_default(self) -> None:
        raw = {"type": "dispatch_start"}
        event = parse_event(raw)
        assert isinstance(event, DispatchStart)
        assert event.dispatch_id == ""
        assert event.session_id == ""
        assert event.turn_id == ""


class TestParseRunOutputChunk:
    """run_output_chunk events parse into RunOutputChunk."""

    def test_text_content(self) -> None:
        raw = {
            "type": "run_output_chunk",
            "run_id": "r-10",
            "agent": "homelab",
            "content": "Here is the answer...",
            "final": False,
        }
        event = parse_event(raw)
        assert isinstance(event, RunOutputChunk)
        assert event.run_id == "r-10"
        assert event.agent == "homelab"
        assert event.content == "Here is the answer..."
        assert event.final is False

    def test_final_chunk(self) -> None:
        raw = {
            "type": "run_output_chunk",
            "run_id": "r-10",
            "agent": "homelab",
            "content": "",
            "final": True,
        }
        event = parse_event(raw)
        assert isinstance(event, RunOutputChunk)
        assert event.final is True

    def test_defaults(self) -> None:
        raw = {"type": "run_output_chunk"}
        event = parse_event(raw)
        assert isinstance(event, RunOutputChunk)
        assert event.content == ""
        assert event.final is False
        assert event.agent == ""
        assert event.run_id == ""


class TestParseToolStart:
    """tool_start events parse into ToolStart."""

    def test_full_payload(self) -> None:
        raw = {
            "type": "tool_start",
            "tool": "Read",
            "tool_id": "tid-99",
            "run_id": "r-5",
            "agent": "work",
            "input": {"file_path": "/tmp/test.txt"},
        }
        event = parse_event(raw)
        assert isinstance(event, ToolStart)
        assert event.tool == "Read"
        assert event.tool_id == "tid-99"
        assert event.run_id == "r-5"
        assert event.agent == "work"
        assert event.input == {"file_path": "/tmp/test.txt"}

    def test_defaults(self) -> None:
        raw = {"type": "tool_start"}
        event = parse_event(raw)
        assert isinstance(event, ToolStart)
        assert event.tool == ""
        assert event.tool_id == ""
        assert event.input == {}


class TestParseConfirmRequest:
    """confirm_request events parse into ConfirmRequest."""

    def test_full_payload(self) -> None:
        raw = {
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-42",
            "run_id": "r-7",
            "agent": "homelab",
            "input": {"command": "rm -rf /"},
            "risk": "high",
        }
        event = parse_event(raw)
        assert isinstance(event, ConfirmRequest)
        assert event.tool == "Bash"
        assert event.tool_id == "tid-42"
        assert event.run_id == "r-7"
        assert event.agent == "homelab"
        assert event.input == {"command": "rm -rf /"}
        assert event.risk == "high"

    def test_defaults(self) -> None:
        raw = {"type": "confirm_request"}
        event = parse_event(raw)
        assert isinstance(event, ConfirmRequest)
        assert event.risk == ""
        assert event.input == {}


class TestParseRunPhase:
    """run_phase events parse into RunPhase."""

    def test_full_payload(self) -> None:
        raw = {
            "type": "run_phase",
            "run_id": "r-3",
            "agent": "finance",
            "phase": "executing",
            "summary": "Running Firefly query",
        }
        event = parse_event(raw)
        assert isinstance(event, RunPhase)
        assert event.phase == "executing"
        assert event.summary == "Running Firefly query"
        assert event.run_id == "r-3"
        assert event.agent == "finance"

    def test_defaults(self) -> None:
        raw = {"type": "run_phase"}
        event = parse_event(raw)
        assert isinstance(event, RunPhase)
        assert event.phase == ""
        assert event.summary == ""


class TestParseUnknownEvent:
    """Unknown event types fall back to base ProtocolEvent."""

    def test_unknown_type(self) -> None:
        raw = {"type": "some_future_event", "data": 42}
        event = parse_event(raw)
        assert type(event) is ProtocolEvent
        assert event.type == "some_future_event"
        assert event.raw is raw

    def test_missing_type(self) -> None:
        raw = {"data": "no type field"}
        event = parse_event(raw)
        assert type(event) is ProtocolEvent
        assert event.type == ""


class TestParseErrorEvent:
    """error events parse into ErrorEvent."""

    def test_full_payload(self) -> None:
        raw = {
            "type": "error",
            "message": "Something went wrong",
            "code": "TIMEOUT",
            "agent": "work",
        }
        event = parse_event(raw)
        assert isinstance(event, ErrorEvent)
        assert event.message == "Something went wrong"
        assert event.code == "TIMEOUT"
        assert event.agent == "work"

    def test_defaults(self) -> None:
        raw = {"type": "error"}
        event = parse_event(raw)
        assert isinstance(event, ErrorEvent)
        assert event.message == ""
        assert event.code == ""


class TestRawPreserved:
    """Every parsed event preserves the original raw dict."""

    @pytest.mark.parametrize("event_type", [
        "dispatch_start",
        "run_output_chunk",
        "tool_start",
        "confirm_request",
        "run_phase",
        "error",
    ])
    def test_raw_identity(self, event_type: str) -> None:
        raw = {"type": event_type}
        event = parse_event(raw)
        assert event.raw is raw
