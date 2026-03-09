"""Typed event dataclasses matching the Corvus WebSocket protocol.

Each WebSocket message is a JSON dict with a ``type`` field.  ``parse_event``
maps that type string to a concrete dataclass so the TUI can pattern-match
on strongly-typed objects instead of raw dicts.
"""

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ProtocolEvent:
    """Fallback for any event type not explicitly modelled."""

    type: str = ""
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dispatch lifecycle
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DispatchStart(ProtocolEvent):
    """Router has begun dispatching a user message."""

    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


@dataclass(slots=True)
class DispatchPlan(ProtocolEvent):
    """Router announces the execution plan (which agents, tasks)."""

    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    tasks: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class DispatchComplete(ProtocolEvent):
    """All tasks in the dispatch have finished."""

    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    result: str = ""
    summary: str = ""


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RunStart(ProtocolEvent):
    """An agent run has started."""

    run_id: str = ""
    agent: str = ""
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    task_id: str = ""


@dataclass(slots=True)
class RunPhase(ProtocolEvent):
    """An agent run transitioned to a new phase (thinking, executing, etc.)."""

    run_id: str = ""
    agent: str = ""
    phase: str = ""
    summary: str = ""
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


@dataclass(slots=True)
class RunOutputChunk(ProtocolEvent):
    """A chunk of streaming text output from an agent run."""

    run_id: str = ""
    agent: str = ""
    content: str = ""
    final: bool = False
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


@dataclass(slots=True)
class RunComplete(ProtocolEvent):
    """An agent run has finished."""

    run_id: str = ""
    agent: str = ""
    result: str = ""
    summary: str = ""
    cost_usd: float = 0.0
    tokens_used: int = 0
    context_pct: float = 0.0
    context_limit: int = 0
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


# ---------------------------------------------------------------------------
# Tool events
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ToolStart(ProtocolEvent):
    """An agent is invoking a tool."""

    tool: str = ""
    tool_id: str = ""
    run_id: str = ""
    agent: str = ""
    input: dict = field(default_factory=dict)
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


@dataclass(slots=True)
class ToolResult(ProtocolEvent):
    """A tool invocation has completed."""

    tool: str = ""
    tool_id: str = ""
    run_id: str = ""
    agent: str = ""
    status: str = ""
    output: Any = None
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


# ---------------------------------------------------------------------------
# Confirmation flow
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ConfirmRequest(ProtocolEvent):
    """The gateway is asking the user to approve a tool call."""

    tool: str = ""
    tool_id: str = ""
    run_id: str = ""
    agent: str = ""
    input: dict = field(default_factory=dict)
    risk: str = ""
    dispatch_id: str = ""
    session_id: str = ""
    turn_id: str = ""


@dataclass(slots=True)
class ConfirmResponse(ProtocolEvent):
    """The user's response to a confirmation request."""

    tool_id: str = ""
    run_id: str = ""
    approved: bool = False


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ErrorEvent(ProtocolEvent):
    """An error occurred in the gateway."""

    message: str = ""
    code: str = ""
    agent: str = ""
    run_id: str = ""
    dispatch_id: str = ""
    session_id: str = ""


# ---------------------------------------------------------------------------
# Type map and parser
# ---------------------------------------------------------------------------

_EVENT_TYPE_MAP: dict[str, type[ProtocolEvent]] = {
    "dispatch_start": DispatchStart,
    "dispatch_plan": DispatchPlan,
    "dispatch_complete": DispatchComplete,
    "run_start": RunStart,
    "run_phase": RunPhase,
    "run_output_chunk": RunOutputChunk,
    "run_complete": RunComplete,
    "tool_start": ToolStart,
    "tool_result": ToolResult,
    "confirm_request": ConfirmRequest,
    "confirm_response": ConfirmResponse,
    "error": ErrorEvent,
}


# Server-emitted field names that differ from TUI dataclass field names.
# Maps (event_type, server_field) → dataclass_field.
_FIELD_ALIASES: dict[tuple[str, str], str] = {
    ("tool_start", "call_id"): "tool_id",
    ("tool_start", "params"): "input",
    ("tool_result", "call_id"): "tool_id",
    ("tool_result", "tool_call_id"): "tool_id",
    ("tool_result", "content"): "output",
}


def parse_event(raw: dict) -> ProtocolEvent:
    """Parse a raw WebSocket dict into a typed ProtocolEvent subclass.

    Unknown event types return a base ``ProtocolEvent`` so the caller never
    has to handle ``None``.  Server-side field names that differ from the
    TUI dataclass fields are normalized via ``_FIELD_ALIASES``.
    """
    event_type = raw.get("type", "")
    cls = _EVENT_TYPE_MAP.get(event_type, ProtocolEvent)

    # Build kwargs from raw dict, only including fields the dataclass declares
    cls_fields = {f.name for f in cls.__dataclass_fields__.values()}
    kwargs: dict[str, Any] = {"type": event_type, "raw": raw}
    for key, value in raw.items():
        # Normalize aliased field names
        mapped_key = _FIELD_ALIASES.get((event_type, key), key)
        if mapped_key in cls_fields and mapped_key not in ("type", "raw"):
            kwargs[mapped_key] = value

    return cls(**kwargs)
