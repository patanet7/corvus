"""ACP Event Translator — converts ACP session/update notifications into Corvus WebSocket events.

The frontend receives identical event shapes regardless of whether the backend
is Claude (native) or an ACP-compatible agent (Codex CLI, Gemini CLI, etc.).
Each ACP ``sessionUpdate`` type maps to one or more Corvus WebSocket event dicts.

ACP spec: session/update params contain ``sessionId`` and ``update`` where
``update.sessionUpdate`` is the discriminator (e.g. "agent_message_chunk",
"tool_call", "plan").  Content is a ContentBlock ``{type: "text", text: "..."}``.
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
    """Return the common fields present in every Corvus WebSocket event."""
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


def _extract_text(content: Any) -> str:
    """Extract text from an ACP ContentBlock or raw string."""
    if isinstance(content, dict):
        return content.get("text", "")
    if isinstance(content, str):
        return content
    return ""


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

    The ACP ``update`` dict uses ``sessionUpdate`` as the discriminator field.

    Args:
        update: Raw ACP update dict from session/update params.update.
        run_id: Corvus run identifier.
        session_id: Corvus session identifier.
        turn_id: Current conversation turn identifier.
        dispatch_id: Dispatch identifier for this route.
        agent: Name of the domain agent handling the request.
        model: Model identifier used by the ACP agent.
        chunk_index: Sequence number for output chunks.
        route_payload: Additional routing metadata spread into each event.

    Returns:
        List of Corvus WebSocket event dicts. Empty list for unknown types.
    """
    update_type: str = update.get("sessionUpdate", "")
    base = _base_fields(
        run_id=run_id,
        session_id=session_id,
        turn_id=turn_id,
        dispatch_id=dispatch_id,
        agent=agent,
        model=model,
        route_payload=route_payload,
    )

    if update_type == "agent_message_chunk":
        content = sanitize(_extract_text(update.get("content", "")))
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

    if update_type == "agent_thought_chunk":
        content = sanitize(_extract_text(update.get("content", "")))
        return [
            {
                **base,
                "type": "thinking",
                "content": content,
            },
        ]

    if update_type == "tool_call":
        return [
            {
                **base,
                "type": "tool_use",
                "tool_name": update.get("title", "unknown"),
                "tool_call_id": update.get("toolCallId", ""),
                "kind": update.get("kind", ""),
                "status": update.get("status", "pending"),
            },
        ]

    if update_type == "tool_call_update":
        # Content is an array of ToolCallContent items
        raw_content = update.get("content", [])
        text_parts = []
        if isinstance(raw_content, list):
            for item in raw_content:
                if isinstance(item, dict) and "content" in item:
                    text_parts.append(_extract_text(item["content"]))
        content = sanitize("\n".join(text_parts))
        return [
            {
                **base,
                "type": "tool_result",
                "tool_call_id": update.get("toolCallId", ""),
                "status": update.get("status", ""),
                "content": content,
            },
        ]

    if update_type == "plan":
        entries = update.get("entries", [])
        summary = "; ".join(
            f"[{e.get('status', '?')}] {e.get('content', '')}"
            for e in entries
            if isinstance(e, dict)
        )
        return [
            {
                **base,
                "type": "task_progress",
                "status": "planning",
                "summary": sanitize(summary),
                "entries": entries,
            },
        ]

    if update_type in ("available_commands_update", "current_mode_update", "config_options_update"):
        return [
            {
                **base,
                "type": "agent_status",
                "acp_kind": update_type,
                "data": {k: v for k, v in update.items() if k != "sessionUpdate"},
            },
        ]

    # Unknown update types are silently ignored.
    return []
