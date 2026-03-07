"""Security and logging hooks for the Corvus gateway.

Uses HookMatcher from claude_agent_sdk to intercept tool calls.
"""

import logging
import re
import time
import uuid as _uuid
from collections.abc import Awaitable, Callable
from typing import Any

from corvus.events import EventEmitter

logger = logging.getLogger("corvus-gateway")

# Type alias for WebSocket forwarding callback
WSCallback = Callable[[dict], Awaitable[None]]

# --- Security check functions (pure, testable) ---

ENV_PATTERNS = re.compile(
    r"cat\s+.*\.env|head\s+.*\.env|tail\s+.*\.env|"
    r"less\s+.*\.env|more\s+.*\.env|strings\s+.*\.env|"
    r"source\s+.*\.env|\.\s+.*\.env|"
    r"sed\s+.*\.env|awk\s+.*\.env|"
    r"grep\s+.*\.env.*secret|"
    r"find\s+.*\.env.*-exec|"
    r"\.secrets/|"
    r"(^|\s)(printenv|env)(\s|$)|"
    r"(^|\s)set(\s|$)",
    re.IGNORECASE,
)


def check_bash_safety(command: str) -> str:
    """Check if a Bash command is safe to execute. Returns 'ALLOWED' or 'BLOCKED'."""
    if ENV_PATTERNS.search(command):
        return "BLOCKED"
    return "ALLOWED"


def check_read_safety(file_path: str) -> str:
    """Check if a file path is safe to read. Returns 'ALLOWED' or 'BLOCKED'."""
    if file_path.endswith(".env") or "/.env" in file_path or ".secrets/" in file_path:
        return "BLOCKED"
    return "ALLOWED"


# --- EventEmitter-based hook factory ---


def create_hooks(
    emitter: EventEmitter,
    *,
    ws_callback: WSCallback | None = None,
    confirm_gated: set[str] | None = None,
    allow_secret_access: bool = False,
) -> dict:
    """Create hook functions that emit events via the given EventEmitter.

    Args:
        emitter: EventEmitter for structured event logging.
        ws_callback: Optional async callable(msg_dict) for WebSocket forwarding.
            When provided, tool_start and tool_result messages are forwarded to
            the connected WebSocket client.
        confirm_gated: Deprecated/unused in hooks. Confirm-gating is now handled
            by the can_use_tool callback in options.py via ConfirmQueue. Kept for
            backward compatibility of the function signature.
        allow_secret_access: When True, bypass .env / secrets security blocks
            (break-glass mode).

    Returns dict with 'pre_tool_use' and 'post_tool_use' async callables.
    """
    gated_tools = confirm_gated if confirm_gated is not None else set()

    # Shared context between pre and post hooks so tool_result call_id
    # matches the tool_start call_id for the same invocation.
    # Keyed by tool_use_id (SDK-provided) for correct correlation.
    _tool_call_context: dict[str, dict] = {}

    async def pre_tool_use(
        input_data: dict[str, Any], tool_use_id: str, context: dict[str, Any] | None
    ) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Bash safety check
        command = tool_input.get("command", "")
        if not allow_secret_access and command and check_bash_safety(command) == "BLOCKED":
            await emitter.emit("security_block", tool=tool_name, reason="env_read", tool_use_id=tool_use_id)
            return {"decision": "block", "reason": "Reading .env files or secrets is prohibited."}

        # Read safety check
        file_path = tool_input.get("file_path", "")
        if not allow_secret_access and file_path and check_read_safety(file_path) == "BLOCKED":
            await emitter.emit("security_block", tool=tool_name, reason="env_read", tool_use_id=tool_use_id)
            return {"decision": "block", "reason": "Reading .env files is prohibited."}

        # Use SDK tool_use_id as call_id when available, otherwise generate one.
        call_id = tool_use_id if tool_use_id else str(_uuid.uuid4())[:8]

        # Store context for the post hook to retrieve
        _tool_call_context[tool_use_id] = {
            "call_id": call_id,
            "start_time": time.monotonic(),
        }

        # Confirm-gating is handled by can_use_tool callback (options.py).

        # Emit tool_start for frontend (non-blocked, non-gated tools)
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
            duration_ms = int((time.monotonic() - ctx["start_time"]) * 1000)
        else:
            call_id = tool_use_id if tool_use_id else str(_uuid.uuid4())[:8]
            duration_ms = 0

        # Extract output from input_data if the SDK provides it;
        # fall back to a placeholder instead of misleadingly sending the input.
        tool_output = input_data.get("tool_result", input_data.get("output", None))
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
                    "call_id": call_id,
                    "output": output_str,
                    "duration_ms": duration_ms,
                    "status": status,
                }
            )

        return {}

    return {"pre_tool_use": pre_tool_use, "post_tool_use": post_tool_use}
