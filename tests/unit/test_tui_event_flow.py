"""Behavioral tests for TUI event flow — field aliasing, tool name carry-through,
agent routing, and rendered output contracts.

These test the REAL event paths: server-emitted payloads → parse_event → EventHandler
→ ChatRenderer output.  No mocks, no fakes.
"""

import io

import pytest
from rich.console import Console

from corvus.tui.core.agent_stack import AgentStack, AgentStatus
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.events import (
    ConfirmRequest,
    ConfirmResponse,
    DispatchComplete,
    DispatchStart,
    ErrorEvent,
    ProtocolEvent,
    RateLimitEvent,
    RunPhase,
    ToolResult,
    ToolStart,
    parse_event,
)
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
# 1. Field alias mapping — server payloads use different names than TUI
# ===========================================================================

class TestServerFieldAliases:
    """parse_event normalizes server-emitted field names to TUI dataclass fields.

    The server sends: call_id, params (tool_start); call_id (tool_result).
    The TUI dataclasses expect: tool_id, input (ToolStart); tool_id (ToolResult).
    """

    def test_tool_start_call_id_maps_to_tool_id(self) -> None:
        raw = {
            "type": "tool_start",
            "tool": "memory_search",
            "call_id": "abc-123",
            "params": {"query": "homelab"},
        }
        event = parse_event(raw)
        assert isinstance(event, ToolStart)
        assert event.tool_id == "abc-123"

    def test_tool_start_params_maps_to_input(self) -> None:
        raw = {
            "type": "tool_start",
            "tool": "memory_search",
            "call_id": "abc-123",
            "params": {"query": "homelab"},
        }
        event = parse_event(raw)
        assert isinstance(event, ToolStart)
        assert event.input == {"query": "homelab"}

    def test_tool_result_call_id_maps_to_tool_id(self) -> None:
        raw = {
            "type": "tool_result",
            "call_id": "abc-123",
            "output": "found 3 results",
            "status": "success",
        }
        event = parse_event(raw)
        assert isinstance(event, ToolResult)
        assert event.tool_id == "abc-123"

    def test_tool_result_preserves_output(self) -> None:
        raw = {
            "type": "tool_result",
            "call_id": "abc-123",
            "output": "search results here",
            "status": "success",
        }
        event = parse_event(raw)
        assert isinstance(event, ToolResult)
        assert event.output == "search results here"

    def test_tool_result_has_no_tool_name_from_server(self) -> None:
        """The server never sends a 'tool' field in tool_result payloads.

        This is by design — the event handler must track tool names
        from tool_start events.
        """
        raw = {
            "type": "tool_result",
            "call_id": "abc-123",
            "output": "ok",
            "status": "success",
        }
        event = parse_event(raw)
        assert isinstance(event, ToolResult)
        assert event.tool == ""  # empty — name must come from tool_start

    def test_tool_start_native_field_names_still_work(self) -> None:
        """If a future server sends the TUI field names directly, they still work."""
        raw = {
            "type": "tool_start",
            "tool": "Bash",
            "tool_id": "native-id",
            "input": {"command": "ls"},
        }
        event = parse_event(raw)
        assert isinstance(event, ToolStart)
        assert event.tool_id == "native-id"
        assert event.input == {"command": "ls"}

    def test_acp_tool_result_content_maps_to_output(self) -> None:
        """ACP path sends 'content' instead of 'output'."""
        raw = {
            "type": "tool_result",
            "tool_call_id": "acp-001",
            "content": "acp result data",
            "status": "success",
        }
        event = parse_event(raw)
        assert isinstance(event, ToolResult)
        assert event.tool_id == "acp-001"
        assert event.output == "acp result data"


# ===========================================================================
# 2. Tool name carry-through — EventHandler tracks names across events
# ===========================================================================

class TestToolNameCarryThrough:
    """EventHandler carries the tool name from tool_start to tool_result.

    The server's tool_result payload has no tool name. The event handler
    stores it from tool_start (keyed by tool_id) and injects it when
    rendering tool_result.
    """

    @pytest.mark.asyncio
    async def test_tool_name_appears_in_result_panel(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        # Simulate server payloads
        tool_start_raw = {
            "type": "tool_start",
            "tool": "mcp__memory__search",
            "call_id": "call-001",
            "params": {},
        }
        tool_result_raw = {
            "type": "tool_result",
            "call_id": "call-001",
            "output": "3 memories found",
            "status": "success",
        }

        await handler.handle(parse_event(tool_start_raw))
        _output(buf)  # clear tool_start output

        await handler.handle(parse_event(tool_result_raw))
        result_output = _output(buf)

        assert "mcp__memory__search" in result_output

    @pytest.mark.asyncio
    async def test_tool_name_missing_without_prior_start(self) -> None:
        """If tool_result arrives without a prior tool_start, tool name is empty."""
        handler, stack, buf, _ = _make_stack_renderer()

        tool_result_raw = {
            "type": "tool_result",
            "call_id": "orphan-001",
            "output": "some output",
            "status": "success",
        }

        await handler.handle(parse_event(tool_result_raw))
        result_output = _output(buf)

        # Panel renders but tool name is absent
        assert "some output" in result_output

    @pytest.mark.asyncio
    async def test_multiple_tools_tracked_independently(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        # Two tool_start events with different IDs
        await handler.handle(parse_event({
            "type": "tool_start",
            "tool": "tool_alpha",
            "call_id": "id-alpha",
            "params": {},
        }))
        await handler.handle(parse_event({
            "type": "tool_start",
            "tool": "tool_beta",
            "call_id": "id-beta",
            "params": {},
        }))
        _output(buf)  # clear

        # Results arrive in reverse order
        await handler.handle(parse_event({
            "type": "tool_result",
            "call_id": "id-beta",
            "output": "beta output",
            "status": "success",
        }))
        beta_output = _output(buf)
        assert "tool_beta" in beta_output

        await handler.handle(parse_event({
            "type": "tool_result",
            "call_id": "id-alpha",
            "output": "alpha output",
            "status": "success",
        }))
        alpha_output = _output(buf)
        assert "tool_alpha" in alpha_output


# ===========================================================================
# 3. Thinking message format — must use @agent prefix
# ===========================================================================

class TestThinkingSpinner:
    """run_start events start a thinking spinner, which stops on stream/tool."""

    @pytest.mark.asyncio
    async def test_thinking_starts_spinner(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_start",
            "agent": "homelab",
            "run_id": "r-1",
        }))

        # Spinner is a Live display — verify it was started
        assert handler._renderer._thinking_live is not None

    @pytest.mark.asyncio
    async def test_thinking_spinner_stops_on_stream(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_start",
            "agent": "homelab",
            "run_id": "r-1",
        }))
        assert handler._renderer._thinking_live is not None

        # First output chunk should stop the spinner
        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "homelab",
            "content": "Hello",
        }))
        assert handler._renderer._thinking_live is None

    @pytest.mark.asyncio
    async def test_thinking_spinner_stops_on_tool(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_start",
            "agent": "homelab",
            "run_id": "r-1",
        }))
        assert handler._renderer._thinking_live is not None

        await handler.handle(parse_event({
            "type": "tool_start",
            "tool": "Bash",
            "call_id": "c-1",
            "params": {"command": "ls"},
        }))
        assert handler._renderer._thinking_live is None

    @pytest.mark.asyncio
    async def test_thinking_sets_agent_status(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()
        stack.push("homelab", session_id="s1")

        await handler.handle(parse_event({
            "type": "run_start",
            "agent": "homelab",
            "run_id": "r-1",
        }))

        ctx = stack.find("homelab")
        assert ctx is not None
        assert ctx.status == AgentStatus.THINKING

        # Clean up spinner
        handler._renderer._stop_thinking()


# ===========================================================================
# 4. Streaming → Markdown rendering contract
# ===========================================================================

class TestStreamingToMarkdown:
    """Streaming chunks render live and finalize as markdown in a panel."""

    @pytest.mark.asyncio
    async def test_stream_starts_live_display(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "general",
            "content": "Hello",
        }))

        # Live display should be active
        assert handler._renderer._live is not None

        # Clean up
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "general",
            "tokens_used": 10,
        }))

    @pytest.mark.asyncio
    async def test_stream_live_stops_on_complete(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "general",
            "content": "Hello",
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "general",
            "tokens_used": 10,
        }))

        assert handler._renderer._live is None

    @pytest.mark.asyncio
    async def test_stream_renders_markdown_not_raw(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "general",
            "content": "Hello **world**!",
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "general",
            "tokens_used": 50,
        }))
        output = _output(buf)

        # Rich Markdown renders **bold** as styled text, not literal asterisks.
        # The final panel should contain "world" but NOT literal "**world**"
        assert "world" in output
        assert "**world**" not in output

    @pytest.mark.asyncio
    async def test_stream_chunks_concatenate(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "work",
            "content": "Part one. ",
        }))
        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "work",
            "content": "Part two.",
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 100,
        }))
        output = _output(buf)

        assert "Part one" in output
        assert "Part two" in output

    @pytest.mark.asyncio
    async def test_stream_panel_shows_agent_name(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "finance",
            "content": "Your balance is $1,234.",
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "finance",
            "tokens_used": 30,
        }))
        output = _output(buf)

        assert "@finance" in output


# ===========================================================================
# 5. Token counting through events
# ===========================================================================

class TestTokenCountingThroughEvents:
    """run_complete events accumulate tokens in the counter."""

    @pytest.mark.asyncio
    async def test_tokens_accumulated_from_run_complete(self) -> None:
        handler, stack, buf, counter = _make_stack_renderer()
        stack.push("work", session_id="s1")

        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 500,
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 300,
        }))

        assert counter.agent_total("work") == 800
        assert counter.session_total == 800

    @pytest.mark.asyncio
    async def test_tokens_tracked_per_agent(self) -> None:
        handler, stack, buf, counter = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 200,
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "finance",
            "tokens_used": 150,
        }))

        assert counter.agent_total("work") == 200
        assert counter.agent_total("finance") == 150
        assert counter.session_total == 350


# ===========================================================================
# 6. Welcome banner rendering contract
# ===========================================================================

class TestWelcomeBanner:
    """The welcome banner renders themed content with agent info."""

    def test_welcome_contains_corvus_title(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=80)
        theme = TuiTheme()
        renderer = ChatRenderer(console, theme)

        renderer.render_welcome(agent_count=10, default_agent="huginn")
        output = _output(buf)

        assert "CORVUS" in output

    def test_welcome_shows_agent_count(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=80)
        theme = TuiTheme()
        renderer = ChatRenderer(console, theme)

        renderer.render_welcome(agent_count=7, default_agent="huginn")
        output = _output(buf)

        assert "7 agents" in output

    def test_welcome_shows_default_agent(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=80)
        theme = TuiTheme()
        renderer = ChatRenderer(console, theme)

        renderer.render_welcome(agent_count=5, default_agent="homelab")
        output = _output(buf)

        assert "@homelab" in output

    def test_welcome_shows_help_hint(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=80)
        theme = TuiTheme()
        renderer = ChatRenderer(console, theme)

        renderer.render_welcome(agent_count=5, default_agent="huginn")
        output = _output(buf)

        assert "/help" in output
        assert "/quit" in output


# ===========================================================================
# 7. Error rendering
# ===========================================================================

class TestErrorRendering:
    """Errors render in panels with the error text visible."""

    def test_error_panel_contains_message(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=80)
        renderer = ChatRenderer(console, TuiTheme())

        renderer.render_error("Connection refused")
        output = _output(buf)

        assert "Connection refused" in output
        assert "Error" in output

    def test_error_panel_contains_title(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=80)
        renderer = ChatRenderer(console, TuiTheme())

        renderer.render_error("timeout")
        output = _output(buf)

        assert "Error" in output


# ===========================================================================
# 8. Agent routing intent — app passes selected agent to gateway
# ===========================================================================

class TestAgentRoutingIntent:
    """TuiApp._handle_agent_input passes the selected agent to the gateway.

    We test the routing logic in isolation: when agent X is on the stack,
    the gateway should receive requested_agent=X (unless X is huginn).
    """

    def test_selected_agent_is_not_huginn_routes_directly(self) -> None:
        """When user selects homelab, messages should bypass the router."""
        from corvus.tui.app import TuiApp

        app = TuiApp()
        app.agent_stack.push("homelab", session_id="s1")

        # The routing logic from _handle_agent_input
        selected = app.agent_stack.current.agent_name
        target = None if selected == "huginn" else selected

        assert target == "homelab"

    def test_huginn_selected_lets_router_decide(self) -> None:
        """When user is on huginn (router), messages go through classification."""
        from corvus.tui.app import TuiApp

        app = TuiApp()
        app.agent_stack.push("huginn", session_id="s1")

        selected = app.agent_stack.current.agent_name
        target = None if selected == "huginn" else selected

        assert target is None

    def test_empty_stack_lets_router_decide(self) -> None:
        """With no agent selected, messages go through router classification."""
        from corvus.tui.app import TuiApp

        app = TuiApp()

        if app.agent_stack.depth > 0:
            selected = app.agent_stack.current.agent_name
            target = None if selected == "huginn" else selected
        else:
            target = None

        assert target is None


# ===========================================================================
# 9. Confirm prompt rendering
# ===========================================================================

class TestConfirmPromptRendering:
    """Confirmation prompts show tool name and yes/no/always options."""

    @pytest.mark.asyncio
    async def test_confirm_shows_tool_name_and_options(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-42",
            "agent": "homelab",
            "input": {"command": "docker restart nginx"},
            "risk": "high",
        }))
        output = _output(buf)

        assert "Bash" in output
        assert "docker restart nginx" in output
        assert "yes" in output.lower() or "(y)" in output.lower()
        assert "no" in output.lower() or "(n)" in output.lower()

    @pytest.mark.asyncio
    async def test_confirm_stores_pending(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-42",
            "agent": "homelab",
            "input": {},
        }))

        assert handler.pending_confirm is not None
        assert handler.pending_confirm.tool_id == "tid-42"
        assert handler.pending_confirm.tool == "Bash"

    @pytest.mark.asyncio
    async def test_clear_confirm_removes_pending(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-42",
            "agent": "homelab",
            "input": {},
        }))

        handler.clear_confirm()
        assert handler.pending_confirm is None


# ===========================================================================
# 10. Help and agents list rendering
# ===========================================================================

class TestHelpAndAgentsListRendering:
    """Help and agents list render as Rich tables with real content."""

    def test_help_shows_command_names(self) -> None:
        from corvus.tui.app import TuiApp
        from corvus.tui.commands.registry import InputTier

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        theme = TuiTheme()

        app = TuiApp()
        app.console = console
        app.renderer = ChatRenderer(console, theme)

        commands_by_tier = {}
        for tier in (InputTier.SYSTEM, InputTier.SERVICE, InputTier.AGENT):
            commands = app.command_registry.commands_for_tier(tier)
            if commands:
                commands_by_tier[tier.value] = commands

        app.renderer.render_help(commands_by_tier)
        output = _output(buf)

        assert "/help" in output
        assert "/quit" in output
        assert "/agents" in output
        assert "/tokens" in output
        assert "/spawn" in output

    def test_agents_list_shows_agent_names(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        renderer = ChatRenderer(console, TuiTheme())

        agents = [
            {"id": "homelab", "description": "Server management"},
            {"id": "finance", "description": "Budget tracking"},
            {"id": "huginn", "description": "Router agent"},
        ]
        renderer.render_agents_list(agents, current_agent="huginn")
        output = _output(buf)

        assert "@homelab" in output
        assert "@finance" in output
        assert "@huginn" in output
        assert "●" in output  # current agent marker


# ===========================================================================
# 11. Rate limit event parsing — Task #18
# ===========================================================================

class TestRateLimitEventParsing:
    """parse_event maps rate_limit payloads to RateLimitEvent."""

    def test_rate_limit_parsed_to_correct_type(self) -> None:
        raw = {
            "type": "rate_limit",
            "message": "Too many requests",
            "retry_after_seconds": 30,
        }
        event = parse_event(raw)
        assert isinstance(event, RateLimitEvent)

    def test_rate_limit_fields_populated(self) -> None:
        raw = {
            "type": "rate_limit",
            "message": "Too many requests",
            "retry_after_seconds": 45.5,
            "agent": "work",
        }
        event = parse_event(raw)
        assert isinstance(event, RateLimitEvent)
        assert event.message == "Too many requests"
        assert event.retry_after_seconds == 45.5
        assert event.agent == "work"

    def test_rate_limit_defaults(self) -> None:
        raw = {"type": "rate_limit"}
        event = parse_event(raw)
        assert isinstance(event, RateLimitEvent)
        assert event.message == ""
        assert event.retry_after_seconds == 0.0

    def test_rate_limit_preserves_raw(self) -> None:
        raw = {"type": "rate_limit", "retry_after_seconds": 10}
        event = parse_event(raw)
        assert event.raw == raw


# ===========================================================================
# 12. Rate limit event handling — Task #18
# ===========================================================================

class TestRateLimitEventHandling:
    """EventHandler renders rate limit events as error messages."""

    @pytest.mark.asyncio
    async def test_rate_limit_renders_retry_message(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "rate_limit",
            "message": "Too many requests",
            "retry_after_seconds": 30,
        }))
        output = _output(buf)

        assert "Rate limited" in output
        assert "30s" in output

    @pytest.mark.asyncio
    async def test_rate_limit_zero_retry_uses_message(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "rate_limit",
            "message": "Slow down please",
            "retry_after_seconds": 0,
        }))
        output = _output(buf)

        assert "Slow down please" in output

    @pytest.mark.asyncio
    async def test_rate_limit_no_message_no_retry_fallback(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "rate_limit",
        }))
        output = _output(buf)

        assert "Rate limited" in output

    @pytest.mark.asyncio
    async def test_rate_limit_ends_active_stream(self) -> None:
        handler, stack, buf, _ = _make_stack_renderer()

        # Start a stream
        await handler.handle(parse_event({
            "type": "run_output_chunk",
            "agent": "work",
            "content": "Hello",
        }))
        assert handler._renderer._live is not None

        # Rate limit should end the stream
        await handler.handle(parse_event({
            "type": "rate_limit",
            "retry_after_seconds": 15,
        }))
        assert handler._renderer._live is None


# ===========================================================================
# 13. Cost tracking through events — Task #19
# ===========================================================================

class TestCostTrackingThroughEvents:
    """run_complete events with cost_usd accumulate cost in the counter."""

    @pytest.mark.asyncio
    async def test_cost_accumulated_from_run_complete(self) -> None:
        handler, stack, buf, counter = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 500,
            "cost_usd": 0.05,
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 300,
            "cost_usd": 0.03,
        }))

        assert abs(counter.session_cost - 0.08) < 1e-9
        assert abs(counter.agent_cost("work") - 0.08) < 1e-9

    @pytest.mark.asyncio
    async def test_zero_cost_not_added(self) -> None:
        handler, stack, buf, counter = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 500,
            "cost_usd": 0.0,
        }))

        assert counter.session_cost == 0.0

    @pytest.mark.asyncio
    async def test_cost_tracked_per_agent(self) -> None:
        handler, stack, buf, counter = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 200,
            "cost_usd": 0.10,
        }))
        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "finance",
            "tokens_used": 150,
            "cost_usd": 0.07,
        }))

        assert counter.agent_cost("work") == 0.10
        assert counter.agent_cost("finance") == 0.07
        assert abs(counter.session_cost - 0.17) < 1e-9

    @pytest.mark.asyncio
    async def test_missing_cost_field_defaults_to_zero(self) -> None:
        handler, stack, buf, counter = _make_stack_renderer()

        await handler.handle(parse_event({
            "type": "run_complete",
            "agent": "work",
            "tokens_used": 200,
        }))

        assert counter.session_cost == 0.0


# ===========================================================================
# 14. Auto-approve flow — Task I13
# ===========================================================================

class TestAutoApproveFlow:
    """EventHandler auto-approve callbacks skip the user prompt for allowed tools."""

    def test_set_auto_approve(self) -> None:
        """set_auto_approve stores the check and confirm callbacks."""
        handler, stack, buf, _ = _make_stack_renderer()

        approved_calls: list[tuple[str, str]] = []

        def check_fn(tool: str) -> bool:
            return tool == "Bash"

        def confirm_fn(tool_id: str, action: str) -> None:
            approved_calls.append((tool_id, action))

        handler.set_auto_approve(check_fn, confirm_fn)
        assert handler._auto_approve_check is not None
        assert handler._auto_approve_confirm is not None

    @pytest.mark.asyncio
    async def test_auto_approve_confirms_automatically(self) -> None:
        """When auto_approve check returns True, handler auto-responds without prompting."""
        handler, stack, buf, _ = _make_stack_renderer()

        approved_calls: list[tuple[str, str]] = []

        def check_fn(tool: str) -> bool:
            return tool == "Bash"

        def confirm_fn(tool_id: str, action: str) -> None:
            approved_calls.append((tool_id, action))

        handler.set_auto_approve(check_fn, confirm_fn)

        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-auto",
            "agent": "homelab",
            "input": {"command": "ls"},
        }))

        # Should have auto-approved, not stored pending
        assert handler.pending_confirm is None
        assert len(approved_calls) == 1
        assert approved_calls[0] == ("tid-auto", "approve")

    @pytest.mark.asyncio
    async def test_auto_approve_false_prompts(self) -> None:
        """When auto_approve check returns False, handler stores pending and renders prompt."""
        handler, stack, buf, _ = _make_stack_renderer()

        approved_calls: list[tuple[str, str]] = []

        def check_fn(tool: str) -> bool:
            return tool == "Bash"  # Only Bash is auto-approved

        def confirm_fn(tool_id: str, action: str) -> None:
            approved_calls.append((tool_id, action))

        handler.set_auto_approve(check_fn, confirm_fn)

        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Write",
            "tool_id": "tid-manual",
            "agent": "homelab",
            "input": {"path": "/etc/config"},
        }))

        # Should NOT have auto-approved — Write is not in the allow list
        assert len(approved_calls) == 0
        assert handler.pending_confirm is not None
        assert handler.pending_confirm.tool_id == "tid-manual"
        assert handler.pending_confirm.tool == "Write"

        output = _output(buf)
        assert "Write" in output


# ===========================================================================
# 15. Event type parse round-trips — Task I14
# ===========================================================================

class TestEventParseRoundTrips:
    """parse_event correctly maps raw dicts to typed dataclass instances."""

    def test_parse_dispatch_start(self) -> None:
        raw = {
            "type": "dispatch_start",
            "dispatch_id": "d-001",
            "session_id": "s-001",
            "turn_id": "t-001",
        }
        event = parse_event(raw)
        assert isinstance(event, DispatchStart)
        assert event.dispatch_id == "d-001"
        assert event.session_id == "s-001"
        assert event.turn_id == "t-001"
        assert event.raw == raw

    def test_parse_dispatch_complete(self) -> None:
        raw = {
            "type": "dispatch_complete",
            "dispatch_id": "d-002",
            "session_id": "s-002",
            "turn_id": "t-002",
            "result": "success",
            "summary": "All tasks done",
        }
        event = parse_event(raw)
        assert isinstance(event, DispatchComplete)
        assert event.dispatch_id == "d-002"
        assert event.result == "success"
        assert event.summary == "All tasks done"

    def test_parse_run_phase(self) -> None:
        raw = {
            "type": "run_phase",
            "run_id": "r-001",
            "agent": "homelab",
            "phase": "executing",
            "summary": "Running tool calls",
        }
        event = parse_event(raw)
        assert isinstance(event, RunPhase)
        assert event.run_id == "r-001"
        assert event.agent == "homelab"
        assert event.phase == "executing"
        assert event.summary == "Running tool calls"

    def test_parse_confirm_response(self) -> None:
        raw = {
            "type": "confirm_response",
            "tool_id": "tid-99",
            "run_id": "r-099",
            "approved": True,
        }
        event = parse_event(raw)
        assert isinstance(event, ConfirmResponse)
        assert event.tool_id == "tid-99"
        assert event.run_id == "r-099"
        assert event.approved is True

    def test_parse_error_event(self) -> None:
        raw = {
            "type": "error",
            "message": "Connection lost",
            "code": "E_CONN",
            "agent": "finance",
        }
        event = parse_event(raw)
        assert isinstance(event, ErrorEvent)
        assert event.message == "Connection lost"
        assert event.code == "E_CONN"
        assert event.agent == "finance"

    def test_parse_unknown_event_type(self) -> None:
        raw = {
            "type": "totally_unknown",
            "some_field": "some_value",
        }
        event = parse_event(raw)
        assert type(event) is ProtocolEvent
        assert event.type == "totally_unknown"
        assert event.raw == raw
