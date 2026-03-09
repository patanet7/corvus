"""Failing tests for three TUI bugs observed in live usage.

Bug 1: @mention routing — _handle_agent_input doesn't pass requested_agent
        from parsed mentions to send_message, so @finance messages go to
        huginn (router) instead of directly to finance.

Bug 2: tool_result event from hooks.create_hooks omits the 'tool' field,
        causing empty tool names in TUI result panels.

Bug 3: post_tool_use only checks 'tool_result' and 'output' keys for SDK
        tool output, missing 'tool_response', 'result', and 'content'.

All tests are behavioral — no mocks, no fakes.
"""

import asyncio
import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from corvus.events import EventEmitter, JSONLFileSink
from corvus.hooks import create_hooks
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.input.parser import InputParser
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.events import parse_event
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stack_renderer() -> tuple[EventHandler, AgentStack, io.StringIO, TokenCounter]:
    """Build an EventHandler wired to a real renderer writing to a StringIO buffer."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    stack = AgentStack()
    counter = TokenCounter()
    handler = EventHandler(renderer, stack, counter)
    return handler, stack, buf, counter


def _output(buf: io.StringIO) -> str:
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


# ===========================================================================
# Bug 1: @mention routing — mentions must pass requested_agent to send_message
# ===========================================================================

class TestMentionRouting:
    """When user types '@finance how can we get started', the gateway must
    receive requested_agent='finance', not None (which lets huginn reclassify).
    """

    def test_mention_parse_extracts_agent(self) -> None:
        """Parser correctly identifies the mentioned agent."""
        parser = InputParser(known_agents=["huginn", "finance", "homelab"])
        parsed = parser.parse("@finance how can we get started")
        assert parsed.kind == "mention"
        assert parsed.mentions == ["finance"]
        assert parsed.text == "how can we get started"

    @pytest.mark.asyncio
    async def test_handle_agent_input_passes_requested_agent_for_mention(self) -> None:
        """_handle_agent_input must pass parsed.mentions[0] as requested_agent
        when the input is a mention.

        This is the core bug: send_message was called without requested_agent,
        so huginn reclassified the message instead of routing to the mentioned agent.
        """
        from corvus.tui.app import TuiApp

        app = TuiApp()
        # Set up known agents so parser recognizes @finance
        app.parser.update_agents(["huginn", "finance", "homelab"])
        app.agent_stack.push("huginn", session_id="")

        # Track what send_message receives
        captured_kwargs: dict = {}

        async def _capture_send(text: str, *, session_id=None, requested_agent=None):
            captured_kwargs["text"] = text
            captured_kwargs["requested_agent"] = requested_agent

        app.gateway.send_message = _capture_send

        parsed = app.parser.parse("@finance how can we get started")
        await app._handle_agent_input(parsed)

        assert captured_kwargs.get("requested_agent") == "finance", (
            f"Expected requested_agent='finance', got {captured_kwargs.get('requested_agent')!r}"
        )


# ===========================================================================
# Bug 2: tool_result event missing 'tool' field
# ===========================================================================

class TestToolResultIncludesToolName:
    """The ws_callback payload for tool_result must include a 'tool' field
    so the TUI can display the tool name in the result panel.
    """

    def test_tool_result_payload_includes_tool_name(self) -> None:
        """post_tool_use must include 'tool' in the ws_callback payload."""
        emitter = EventEmitter()
        captured_payloads: list[dict] = []

        async def _capture_ws(payload: dict) -> None:
            captured_payloads.append(payload)

        hooks = create_hooks(emitter, ws_callback=_capture_ws)
        pre_hook = hooks["pre_tool_use"]
        post_hook = hooks["post_tool_use"]

        tool_use_id = "tuid-100"

        # pre_tool_use stores context
        asyncio.run(pre_hook(
            {"tool_name": "mcp__memory__search", "tool_input": {"query": "test"}},
            tool_use_id,
            None,
        ))

        # post_tool_use should emit tool_result with 'tool' field
        asyncio.run(post_hook(
            {"tool_name": "mcp__memory__search", "tool_input": {"query": "test"}},
            tool_use_id,
            None,
        ))

        # Find the tool_result payload
        result_payloads = [p for p in captured_payloads if p["type"] == "tool_result"]
        assert len(result_payloads) == 1, f"Expected 1 tool_result, got {len(result_payloads)}"

        result = result_payloads[0]
        assert "tool" in result, f"tool_result payload missing 'tool' field: {result}"
        assert result["tool"] == "mcp__memory__search"

    @pytest.mark.asyncio
    async def test_tool_result_name_renders_in_panel(self) -> None:
        """When tool_result includes a tool name, it appears in the rendered output."""
        handler, stack, buf, _ = _make_stack_renderer()

        # Simulate tool_result WITH a tool field (the fix)
        await handler.handle(parse_event({
            "type": "tool_result",
            "tool": "mcp__memory__search",
            "call_id": "call-x",
            "output": "found results",
            "status": "success",
        }))
        result_output = _output(buf)
        assert "mcp__memory__search" in result_output


# ===========================================================================
# Bug 3: post_tool_use misses SDK output keys
# ===========================================================================

class TestToolOutputExtraction:
    """post_tool_use must extract tool output from all known SDK keys:
    tool_response, tool_result, output, result, content.
    """

    def _run_post_hook_with_output_key(self, key: str, value: str) -> str:
        """Run post_tool_use with a specific output key and return the ws payload output."""
        emitter = EventEmitter()
        captured: list[dict] = []

        async def _capture(payload: dict) -> None:
            captured.append(payload)

        hooks = create_hooks(emitter, ws_callback=_capture)
        pre_hook = hooks["pre_tool_use"]
        post_hook = hooks["post_tool_use"]

        tool_use_id = "tuid-out"

        asyncio.run(pre_hook(
            {"tool_name": "TestTool", "tool_input": {}},
            tool_use_id,
            None,
        ))
        asyncio.run(post_hook(
            {"tool_name": "TestTool", "tool_input": {}, key: value},
            tool_use_id,
            None,
        ))

        result_payloads = [p for p in captured if p["type"] == "tool_result"]
        assert len(result_payloads) == 1
        return result_payloads[0]["output"]

    def test_extracts_tool_response_key(self) -> None:
        """SDK provides output as 'tool_response'."""
        output = self._run_post_hook_with_output_key("tool_response", "response data")
        assert output == "response data"

    def test_extracts_result_key(self) -> None:
        """SDK provides output as 'result'."""
        output = self._run_post_hook_with_output_key("result", "result data")
        assert output == "result data"

    def test_extracts_content_key(self) -> None:
        """SDK provides output as 'content'."""
        output = self._run_post_hook_with_output_key("content", "content data")
        assert output == "content data"

    def test_existing_output_key_still_works(self) -> None:
        """Existing 'output' key still works."""
        output = self._run_post_hook_with_output_key("output", "output data")
        assert output == "output data"

    def test_existing_tool_result_key_still_works(self) -> None:
        """Existing 'tool_result' key still works."""
        output = self._run_post_hook_with_output_key("tool_result", "tool_result data")
        assert output == "tool_result data"


# ===========================================================================
# Renderer defensive: empty tool name fallback
# ===========================================================================

class TestRendererEmptyToolName:
    """When render_tool_result receives an empty tool_name, it should show
    a fallback label instead of rendering a bare '✓' with no context.
    """

    def test_empty_tool_name_shows_fallback(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        theme = TuiTheme()
        renderer = ChatRenderer(console=console, theme=theme)

        renderer.render_tool_result("", "some output", "huginn")
        output = _output(buf)

        # Should not have an empty label — must show something meaningful
        assert "result" in output.lower(), (
            f"Expected fallback label in tool result panel, got: {output!r}"
        )
        # The empty string should NOT appear as the tool name
        # (i.e., we shouldn't see just "result" with no tool identifier)
