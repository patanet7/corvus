"""ACP Event Translator — converts ACP session/update notifications into Corvus WebSocket events.

The frontend receives identical event shapes regardless of whether the backend
is Claude (native) or an ACP-compatible agent (Codex CLI, Gemini CLI, etc.).
Each ACP update ``kind`` maps to one or more Corvus WebSocket event dicts.
"""

from typing import Any

from corvus.sanitize import sanitize


def _base_fields(
    *,
    run_id: str,
    session_id: str,
    turn_id: str,
    dispatch_id: str,
    agent: str,
    model: str,
    route_payload: dict[str, Any],
) -> dict[str, Any]:
    """Return the common fields present in every Corvus WebSocket event.

    Args:
        run_id: Corvus run identifier.
        session_id: Corvus session identifier.
        turn_id: Current conversation turn identifier.
        dispatch_id: Dispatch identifier for this route.
        agent: Name of the domain agent handling the request.
        model: Model identifier used by the ACP agent.
        route_payload: Additional routing metadata spread into each event.

    Returns:
        Dict of common event fields.
    """
    base: dict[str, Any] = {
        "run_id": run_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "dispatch_id": dispatch_id,
        "agent": agent,
        "model": model,
    }
    base.update(route_payload)
    return base


def translate_acp_update(
    update: dict[str, Any],
    *,
    run_id: str,
    session_id: str,
    turn_id: str,
    dispatch_id: str,
    agent: str,
    model: str,
    chunk_index: int,
    route_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Translate an ACP session/update notification into Corvus WebSocket events.

    Maps ACP update kinds to the Corvus event format so the frontend sees a
    consistent event stream regardless of the backend agent protocol.

    Args:
        update: Raw ACP update dict containing at minimum a ``kind`` field.
        run_id: Corvus run identifier.
        session_id: Corvus session identifier.
        turn_id: Current conversation turn identifier.
        dispatch_id: Dispatch identifier for this route.
        agent: Name of the domain agent handling the request.
        model: Model identifier used by the ACP agent.
        chunk_index: Sequence number for output chunks.
        route_payload: Additional routing metadata spread into each event.

    Returns:
        List of Corvus WebSocket event dicts. Empty list for unknown kinds.
    """
    kind: str = update.get("kind", "")
    base = _base_fields(
        run_id=run_id,
        session_id=session_id,
        turn_id=turn_id,
        dispatch_id=dispatch_id,
        agent=agent,
        model=model,
        route_payload=route_payload,
    )

    if kind == "agent_message_chunk":
        content = sanitize(update.get("content", ""))
        return [
            {
                **base,
                "type": "run_output_chunk",
                "chunk_index": chunk_index,
                "content": content,
                "final": False,
            },
            {
                **base,
                "type": "text",
                "content": content,
            },
        ]

    if kind == "agent_thought_chunk":
        content = sanitize(update.get("content", ""))
        return [
            {
                **base,
                "type": "thinking",
                "content": content,
            },
        ]

    if kind == "tool_call":
        return [
            {
                **base,
                "type": "tool_use",
                "tool_name": update.get("tool_name", "unknown"),
                "tool_call_id": update.get("tool_call_id", ""),
                "description": update.get("description", ""),
                "status": update.get("status", ""),
            },
        ]

    if kind == "tool_call_update":
        content = sanitize(update.get("content", ""))
        return [
            {
                **base,
                "type": "tool_result",
                "tool_call_id": update.get("tool_call_id", ""),
                "status": update.get("status", ""),
                "content": content,
            },
        ]

    if kind == "plan":
        content = sanitize(update.get("content", ""))
        return [
            {
                **base,
                "type": "task_progress",
                "status": "planning",
                "summary": content,
            },
        ]

    if kind in ("available_commands_update", "current_mode_update"):
        return [
            {
                **base,
                "type": "agent_status",
                "acp_kind": kind,
                "data": update.get("data", {}),
            },
        ]

    # Unknown kinds are silently ignored.
    return []
