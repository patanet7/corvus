"""StreamProcessor — translates SDK stream events into Corvus protocol events.

Handles StreamEvent (token-level), AssistantMessage (complete blocks),
UserMessage (checkpoints), and ResultMessage (final metrics).

Design doc: docs/specs/active/2026-03-09-sdk-integration-redesign.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    UserMessage,
)

if TYPE_CHECKING:
    from corvus.gateway.sdk_client_manager import ManagedClient
    from corvus.gateway.session_emitter import SessionEmitter

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
    route_payload: dict[str, Any]


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


class StreamProcessor:
    """Translates SDK stream into Corvus protocol events."""

    def __init__(
        self,
        *,
        emitter: SessionEmitter | None = None,
        managed_client: ManagedClient | None = None,
        context_limit: int = 200000,
    ) -> None:
        self._emitter = emitter
        self._client = managed_client
        self._context_limit = context_limit
        self._text_buffer: str = ""
        self._tool_state: _ToolUseState | None = None
        self._thinking_buffer: str = ""
        self._is_thinking_block: bool = False

    @classmethod
    def _create_for_test(cls) -> StreamProcessor:
        return cls(emitter=None, managed_client=None)

    def _buffer_stream_event(self, event: StreamEvent) -> dict[str, Any]:
        raw = event.event
        is_subagent = event.parent_tool_use_id is not None
        event_type = raw.get("type", "")

        if event_type == "content_block_start":
            block = raw.get("content_block", {})
            block_type = block.get("type")
            if block_type == "tool_use":
                self._tool_state = _ToolUseState(
                    name=block.get("name", ""),
                    id=block.get("id", ""),
                )
                return {"action": "tool_start", "tool": self._tool_state.name, "subagent": is_subagent}
            if block_type == "thinking":
                self._is_thinking_block = True
                return {"action": "thinking_start", "subagent": is_subagent}
            if block_type == "text":
                return {"action": "text_start", "subagent": is_subagent}
            return {"action": "block_start", "block_type": block_type}

        if event_type == "content_block_delta":
            delta = raw.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                self._text_buffer += text
                return {"action": "text_delta", "text": text, "subagent": is_subagent}
            if delta_type == "input_json_delta":
                if self._tool_state:
                    self._tool_state.input_buffer += delta.get("partial_json", "")
                return {"action": "tool_input_delta", "subagent": is_subagent}
            if delta_type == "thinking_delta":
                text = delta.get("thinking", "")
                self._thinking_buffer += text
                return {"action": "thinking_delta", "text": text, "subagent": is_subagent}
            return {"action": "unknown_delta", "delta_type": delta_type}

        if event_type == "content_block_stop":
            if self._tool_state:
                tool_name = self._tool_state.name
                tool_input = self._tool_state.input_buffer
                self._tool_state = None
                return {"action": "tool_complete", "tool": tool_name, "input": tool_input}
            if self._is_thinking_block:
                self._is_thinking_block = False
                thinking = self._thinking_buffer
                self._thinking_buffer = ""
                return {"action": "thinking_complete", "text": thinking}
            return {"action": "text_complete"}

        return {"action": "passthrough", "type": event_type}

    def _build_run_result(
        self,
        *,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float,
        sdk_session_id: str | None,
        context_limit: int | None = None,
    ) -> RunResult:
        limit = context_limit if context_limit is not None else self._context_limit
        tokens_used = tokens_input + tokens_output
        context_pct = round((tokens_used / limit) * 100, 1) if limit > 0 else 0.0
        return RunResult(
            status="success",
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            context_pct=context_pct,
            response_text=self._text_buffer,
            sdk_session_id=sdk_session_id,
            checkpoints=list(self._client.checkpoints) if self._client else [],
        )

    async def process_response(self, ctx: RunContext) -> RunResult:
        if self._client is None or self._client.client is None:
            return RunResult(
                status="error", tokens_used=0, cost_usd=0.0,
                context_pct=0.0, response_text="", sdk_session_id=None, checkpoints=[],
            )
        async for message in self._client.client.receive_response():
            if isinstance(message, StreamEvent):
                action = self._buffer_stream_event(message)
                if self._emitter is not None:
                    await self._emit_action(action, ctx)
            elif isinstance(message, AssistantMessage):
                await self._handle_assistant_message(message, ctx)
            elif isinstance(message, UserMessage):
                if message.uuid:
                    self._client.track_checkpoint(message.uuid)
            elif isinstance(message, ResultMessage):
                usage = getattr(message, "usage", None) or {}
                result = self._build_run_result(
                    tokens_input=int(usage.get("input_tokens", 0)),
                    tokens_output=int(usage.get("output_tokens", 0)),
                    cost_usd=float(getattr(message, "total_cost_usd", 0.0) or 0.0),
                    sdk_session_id=getattr(message, "session_id", None),
                )
                self._client.accumulate(
                    tokens=result.tokens_used,
                    cost_usd=result.cost_usd,
                    sdk_session_id=result.sdk_session_id,
                )
                return result
        return RunResult(
            status="error", tokens_used=0, cost_usd=0.0,
            context_pct=0.0, response_text="", sdk_session_id=None, checkpoints=[],
        )

    async def _handle_assistant_message(self, message: AssistantMessage, ctx: RunContext) -> None:
        for block in message.content:
            if isinstance(block, TextBlock) and block.text:
                # Only emit text that hasn't already been streamed via StreamEvent deltas.
                if not self._text_buffer.endswith(block.text):
                    new_text = block.text
                    self._text_buffer += new_text
                    # Emit as text_delta so the WS client receives the text.
                    if self._emitter is not None:
                        await self._emit_action(
                            {"action": "text_delta", "text": new_text},
                            ctx,
                        )

    async def _emit_action(self, action: dict[str, Any], ctx: RunContext) -> None:
        if self._emitter is None:
            return
        event_type = action.get("action", "")
        payload: dict[str, Any] = {
            "dispatch_id": ctx.dispatch_id,
            "run_id": ctx.run_id,
            "task_id": ctx.task_id,
            "session_id": ctx.session_id,
            "turn_id": ctx.turn_id,
            "agent": ctx.agent_name,
            "model": ctx.model_id,
            **ctx.route_payload,
        }
        if action.get("subagent"):
            payload["subagent"] = True
        if event_type == "text_delta":
            payload["type"] = "text_delta"
            payload["content"] = action["text"]
            await self._emitter.send(payload, persist=True,
                                      run_id=ctx.run_id, dispatch_id=ctx.dispatch_id, turn_id=ctx.turn_id)
        elif event_type == "tool_start":
            payload["type"] = "tool_start"
            payload["tool"] = action["tool"]
            await self._emitter.send(payload, persist=True,
                                      run_id=ctx.run_id, dispatch_id=ctx.dispatch_id, turn_id=ctx.turn_id)
        elif event_type == "tool_complete":
            payload["type"] = "tool_complete"
            payload["tool"] = action["tool"]
            payload["tool_input"] = action.get("input", "")
            await self._emitter.send(payload, persist=True,
                                      run_id=ctx.run_id, dispatch_id=ctx.dispatch_id, turn_id=ctx.turn_id)
        elif event_type == "thinking_delta":
            payload["type"] = "thinking_delta"
            payload["content"] = action["text"]
            await self._emitter.send(payload)
        elif event_type == "thinking_complete":
            payload["type"] = "thinking_complete"
            await self._emitter.send(payload)
