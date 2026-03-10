"""KimiProxy -- translates Anthropic Messages API to Kimi ACP protocol.

Accepts POST /v1/messages in Anthropic Messages format, forwards to K2 via
KimiBridgeClient, and translates K2's ACP streaming responses back to
Anthropic SSE format.

K2 is the MODEL PROVIDER -- we send prompts TO K2 for inference.
This proxy makes K2 look like an Anthropic-compatible API endpoint.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

import structlog

from corvus.kimi_bridge import (
    PromptResult,
    SessionUpdate,
    SessionUpdateType,
    StopReason,
)

logger = structlog.get_logger(__name__)


def create_proxy_app(bridge: Any = None) -> FastAPI:
    """Create the KimiProxy FastAPI app.

    Args:
        bridge: A KimiBridgeClient (or compatible fake for testing).
                If None, must be set via app.state.bridge before use.
    """
    app = FastAPI(title="KimiProxy")
    app.state.bridge = bridge
    app.state.session_id = None

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "kimi-proxy"}

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        stream = body.get("stream", False)
        user_messages = body.get("messages", [])
        system_prompt = body.get("system", "")

        # Extract the last user message text
        prompt_text = _extract_prompt_text(user_messages, system_prompt)

        b = app.state.bridge

        # Ensure session exists
        if not app.state.session_id:
            if not b.initialized:
                await b.initialize()
            session = await b.create_session()
            app.state.session_id = session.session_id

        session_id = app.state.session_id

        if stream:
            return StreamingResponse(
                _stream_sse(b, session_id, prompt_text),
                media_type="text/event-stream",
            )
        else:
            return await _collect_response(b, session_id, prompt_text)

    return app


def _extract_prompt_text(messages: list[dict], system: str = "") -> str:
    """Extract plain text from Anthropic messages format.

    Concatenates system prompt (if present) and all message content
    blocks into a single string for the ACP session/prompt call.
    """
    parts = []
    if system:
        parts.append(system)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block["text"])
    return "\n\n".join(parts)


def _resolve_stop_reason(item: PromptResult) -> str:
    """Extract stop reason string from a PromptResult.

    Handles both StopReason enum values and plain strings.
    """
    sr = item.stop_reason
    if isinstance(sr, StopReason):
        return sr.value
    return str(sr)


async def _stream_sse(bridge: Any, session_id: str, prompt: str):
    """Stream K2's response as Anthropic-compatible SSE events.

    Emits the full Anthropic streaming event sequence:
    message_start -> content_block_start -> content_block_delta* ->
    content_block_stop -> message_delta -> message_stop -> [DONE]
    """
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    block_idx = 0

    # message_start
    yield _sse_event(
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "kimi-k2",
                "stop_reason": None,
            },
        }
    )

    # content_block_start
    yield _sse_event(
        {
            "type": "content_block_start",
            "index": block_idx,
            "content_block": {"type": "text", "text": ""},
        }
    )

    stop_reason = "end_turn"

    async for item in bridge.send_prompt_stream(session_id, prompt):
        if isinstance(item, SessionUpdate):
            if item.update_type == SessionUpdateType.AGENT_MESSAGE_CHUNK.value:
                text = item.text
                if text:
                    yield _sse_event(
                        {
                            "type": "content_block_delta",
                            "index": block_idx,
                            "delta": {"type": "text_delta", "text": text},
                        }
                    )
            elif item.update_type == SessionUpdateType.AGENT_THOUGHT_CHUNK.value:
                # Map thinking chunks to text deltas (K2 thinking -> visible text)
                text = item.text
                if text:
                    yield _sse_event(
                        {
                            "type": "content_block_delta",
                            "index": block_idx,
                            "delta": {"type": "text_delta", "text": text},
                        }
                    )
        elif isinstance(item, PromptResult):
            stop_reason = _resolve_stop_reason(item)

    # content_block_stop
    yield _sse_event(
        {
            "type": "content_block_stop",
            "index": block_idx,
        }
    )

    # message_delta with stop_reason
    yield _sse_event(
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason},
        }
    )

    # message_stop
    yield _sse_event({"type": "message_stop"})

    yield "data: [DONE]\n\n"


async def _collect_response(bridge: Any, session_id: str, prompt: str) -> JSONResponse:
    """Collect full response for non-streaming mode.

    Gathers all streaming chunks into a single Anthropic Messages response.
    """
    text_parts: list[str] = []
    stop_reason = "end_turn"

    async for item in bridge.send_prompt_stream(session_id, prompt):
        if isinstance(item, SessionUpdate):
            if item.update_type in (
                SessionUpdateType.AGENT_MESSAGE_CHUNK.value,
                SessionUpdateType.AGENT_THOUGHT_CHUNK.value,
            ):
                if item.text:
                    text_parts.append(item.text)
        elif isinstance(item, PromptResult):
            stop_reason = _resolve_stop_reason(item)

    return JSONResponse(
        {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "".join(text_parts)}],
            "model": "kimi-k2",
            "stop_reason": stop_reason,
        }
    )


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"
