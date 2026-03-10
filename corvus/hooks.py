"""Event-emitting hooks for the Corvus gateway.

Uses HookMatcher from claude_agent_sdk to intercept tool calls.
Security enforcement (deny lists, secret access) is handled by
permissions.deny + tool_catalog — hooks focus on event emission
and WebSocket forwarding.
"""

import time
import uuid as _uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from corvus.events import EventEmitter

logger = structlog.get_logger(__name__)

# Type alias for WebSocket forwarding callback
WSCallback = Callable[[dict], Awaitable[None]]

# --- EventEmitter-based hook factory ---


def create_hooks(
    emitter: EventEmitter,
    *,
    ws_callback: WSCallback | None = None,
) -> dict:
    """Create hook functions that emit events via the given EventEmitter.

    Args:
        emitter: EventEmitter for structured event logging.
        ws_callback: Optional async callable(msg_dict) for WebSocket forwarding.
            When provided, tool_start and tool_result messages are forwarded to
            the connected WebSocket client.

    Returns dict with 'pre_tool_use' and 'post_tool_use' async callables.
    """
    # Shared context between pre and post hooks so tool_result call_id
    # matches the tool_start call_id for the same invocation.
    # Keyed by tool_use_id (SDK-provided) for correct correlation.
    _tool_call_context: dict[str, dict] = {}

    async def pre_tool_use(
        input_data: dict[str, Any], tool_use_id: str, context: dict[str, Any] | None
    ) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Use SDK tool_use_id as call_id when available, otherwise generate one.
        call_id = tool_use_id if tool_use_id else str(_uuid.uuid4())[:8]

        # Store context for the post hook to retrieve
        _tool_call_context[tool_use_id] = {
            "call_id": call_id,
            "tool_name": tool_name,
            "start_time": time.monotonic(),
        }

        # Emit tool_start for frontend
        if ws_callback:
            await ws_callback(
                {
                    "type": "tool_start",
                    "tool": tool_name,
                    "params": tool_input,
                    "call_id": call_id,
                }
            )

        return {}

    async def post_tool_use(
        input_data: dict[str, Any], tool_use_id: str, context: dict[str, Any] | None
    ) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "unknown")
        tool_input = input_data.get("tool_input", {})

        # Retrieve context stored by pre_tool_use for matching call_id + timing
        ctx = _tool_call_context.pop(tool_use_id, None)
        if ctx:
            call_id = ctx["call_id"]
            ctx_tool_name = ctx.get("tool_name", "")
            duration_ms = int((time.monotonic() - ctx["start_time"]) * 1000)
        else:
            call_id = tool_use_id if tool_use_id else str(_uuid.uuid4())[:8]
            ctx_tool_name = ""
            duration_ms = 0

        # Extract output from input_data — SDK may provide it under various keys.
        tool_output = (
            input_data.get("tool_response")
            or input_data.get("tool_result")
            or input_data.get("output")
            or input_data.get("result")
            or input_data.get("content")
        )
        if tool_output is not None:
            output_str = str(tool_output)[:500]
        else:
            output_str = "(output not captured)"

        # Determine status from SDK data if available
        is_error = input_data.get("is_error", False)
        status = "error" if is_error else "success"

        await emitter.emit(
            "tool_call",
            tool=tool_name,
            tool_use_id=tool_use_id,
            input_summary=str(tool_input)[:200],
        )

        # Emit tool_result for frontend
        if ws_callback:
            await ws_callback(
                {
                    "type": "tool_result",
                    "tool": ctx_tool_name or tool_name,
                    "call_id": call_id,
                    "output": output_str,
                    "duration_ms": duration_ms,
                    "status": status,
                }
            )

        return {}

    return {"pre_tool_use": pre_tool_use, "post_tool_use": post_tool_use}
