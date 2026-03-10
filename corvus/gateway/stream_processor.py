"""StreamProcessor — translates SDK stream events into Corvus protocol events.

Handles StreamEvent (token-level), AssistantMessage (complete blocks),
UserMessage (checkpoints), and ResultMessage (final metrics).

Design doc: docs/specs/active/2026-03-09-sdk-integration-redesign.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("corvus-gateway.stream")


@dataclass
class RunContext:
    """All IDs and metadata a stream processor needs to emit enriched events."""

    dispatch_id: str
    run_id: str
    task_id: str
    session_id: str
    turn_id: str
    agent_name: str
    model_id: str
    route_payload: dict


@dataclass
class RunResult:
    """Outcome of processing a complete response stream."""

    status: str  # "success" | "error" | "interrupted"
    tokens_used: int
    cost_usd: float
    context_pct: float
    response_text: str
    sdk_session_id: str | None
    checkpoints: list[str]


@dataclass
class _ToolUseState:
    """Internal state for tracking an in-progress tool_use block."""

    name: str
    id: str
    input_buffer: str = ""
