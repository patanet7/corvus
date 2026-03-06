"""Shared WebSocket protocol event type definitions.

Single source of truth for all event types emitted over the WebSocket protocol.
Frontend TypeScript types should be synced from this file.
"""

from typing import Literal

# All event types the backend can emit over WebSocket
WS_EVENT_TYPES = Literal[
    "init",
    "routing",
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
    "tool_permission_decision",
    "confirm_request",
    "confirm_response",
    "interrupt_ack",
    "text",
    "done",
    "error",
    "pong",
    "agent_status",
]

# Event type classifications for persistence routing
PERSISTED_SESSION_EVENT_TYPES: frozenset[str] = frozenset({
    "dispatch_start", "dispatch_plan", "dispatch_complete",
    "run_start", "run_phase", "run_output_chunk", "run_complete",
    "task_start", "task_progress", "task_complete",
    "tool_start", "tool_result", "tool_permission_decision",
    "confirm_request", "confirm_response", "interrupt_ack",
})

PERSISTED_RUN_EVENT_TYPES: frozenset[str] = frozenset({
    "run_start", "run_phase", "run_output_chunk", "run_complete",
    "tool_start", "tool_result", "tool_permission_decision",
    "confirm_request", "confirm_response",
})

TRACE_EVENT_TYPES: frozenset[str] = PERSISTED_SESSION_EVENT_TYPES | frozenset({
    "routing", "agent_status", "error",
})
