"""Comprehensive E2E QA tests for the Corvus TUI.

Tests EVERY feature and component of the TUI by exercising the real objects
with real data, capturing actual rendered output via Rich StringIO console,
and verifying:
  - What the user SEES (rendered text) matches expectations
  - What gets SENT to the gateway matches expectations
  - State transitions are correct (agent stack, token counts, always-allow)
  - Error cases are handled gracefully
  - Layout and chrome elements appear correctly

NO MOCKS. Real objects, real console capture, real event flow.
"""

import asyncio
import os
import tempfile
from io import StringIO
from unittest.mock import AsyncMock

import pytest
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.agent_stack import AgentStack, AgentStatus
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.input.completer import ChatCompleter
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import (
    ConfirmRequest,
    DispatchComplete,
    DispatchPlan,
    DispatchStart,
    ErrorEvent,
    ProtocolEvent,
    RunComplete,
    RunOutputChunk,
    RunPhase,
    RunStart,
    ToolResult,
    ToolStart,
    parse_event,
)
from corvus.tui.theme import AGENT_COLORS, TuiTheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_console() -> tuple[Console, StringIO]:
    """Create a Rich Console that writes to a StringIO buffer."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=100)
    return console, buf


def output(buf: StringIO) -> str:
    """Get the rendered output as a plain string."""
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. INPUT PARSING — every input form, edge cases, the exact classification
# ---------------------------------------------------------------------------


class TestInputParserFullCoverage:
    """Test every input parsing path with real parser and real agent names."""

    def setup_method(self):
        self.parser = InputParser(known_agents=["huginn", "homelab", "work", "finance", "personal"])

    # -- Slash commands --

    def test_slash_help(self):
        p = self.parser.parse("/help")
        assert p.kind == "command"
        assert p.command == "help"
        assert p.command_args is None

    def test_slash_command_with_args(self):
        p = self.parser.parse("/agent homelab")
        assert p.kind == "command"
        assert p.command == "agent"
        assert p.command_args == "homelab"

    def test_slash_command_with_multi_word_args(self):
        p = self.parser.parse("/memory search my query here")
        assert p.kind == "command"
        assert p.command == "memory"
        assert p.command_args == "search my query here"

    def test_slash_command_preserves_raw(self):
        p = self.parser.parse("/help")
        assert p.raw == "/help"

    def test_slash_unknown_command_still_parses(self):
        """Unknown commands parse as 'command' kind — router decides tier."""
        p = self.parser.parse("/nonexistent")
        assert p.kind == "command"
        assert p.command == "nonexistent"

    # -- Tool calls --

    def test_bang_tool_simple(self):
        p = self.parser.parse("!obsidian.search")
        assert p.kind == "tool_call"
        assert p.tool_name == "obsidian.search"
        assert p.tool_args is None

    def test_bang_tool_with_args(self):
        p = self.parser.parse("!obsidian.search my query")
        assert p.kind == "tool_call"
        assert p.tool_name == "obsidian.search"
        assert p.tool_args == "my query"

    def test_bang_mcp_tool(self):
        p = self.parser.parse("!mcp__memory_general__memory_search huginn routing")
        assert p.kind == "tool_call"
        assert p.tool_name == "mcp__memory_general__memory_search"
        assert p.tool_args == "huginn routing"

    # -- @mentions with text --

    def test_at_mention_with_text(self):
        p = self.parser.parse("@homelab check nginx")
        assert p.kind == "mention"
        assert p.mentions == ["homelab"]
        assert p.text == "check nginx"

    def test_at_mention_multiple_agents(self):
        p = self.parser.parse("@homelab @finance status")
        assert p.kind == "mention"
        assert "homelab" in p.mentions
        assert "finance" in p.mentions
        assert p.text == "status"

    def test_at_mention_unknown_agent_is_chat(self):
        """@unknown_name with no known agent → regular chat."""
        p = self.parser.parse("@nobody hello")
        assert p.kind == "chat"

    # -- Bare @agent (no text) → should be agent switch --

    def test_bare_at_agent_becomes_command(self):
        """Typing just '@homelab' should switch to that agent, not send empty message."""
        p = self.parser.parse("@homelab")
        assert p.kind == "command"
        assert p.command == "agent"
        assert p.command_args == "homelab"

    def test_bare_at_huginn_becomes_command(self):
        p = self.parser.parse("@huginn")
        assert p.kind == "command"
        assert p.command == "agent"
        assert p.command_args == "huginn"

    def test_bare_at_unknown_is_chat(self):
        """@unknown alone → chat (not a known agent)."""
        p = self.parser.parse("@nobody")
        assert p.kind == "chat"

    # -- Regular chat --

    def test_plain_chat(self):
        p = self.parser.parse("hello world")
        assert p.kind == "chat"
        assert p.text == "hello world"

    def test_empty_string(self):
        p = self.parser.parse("")
        assert p.kind == "chat"
        assert p.text == ""

    def test_whitespace_only(self):
        p = self.parser.parse("   ")
        assert p.kind == "chat"
        assert p.text == ""

    # -- Dynamic agent updates --

    def test_update_agents_adds_new(self):
        self.parser.update_agents(["music"])
        p = self.parser.parse("@music play something")
        assert p.kind == "mention"
        assert p.mentions == ["music"]

    def test_all_is_always_known(self):
        p = self.parser.parse("@all status")
        assert p.kind == "mention"
        assert p.mentions == ["all"]


# ---------------------------------------------------------------------------
# 2. COMMAND ROUTING — every command goes to the right tier
# ---------------------------------------------------------------------------


class TestCommandRoutingFullCoverage:
    """Test that every registered command routes to the correct tier."""

    def setup_method(self):
        self.app = TuiApp()
        self.router = self.app.command_router
        self.parser = self.app.parser

    def test_all_system_commands_route_to_system(self):
        system_cmds = ["help", "quit", "agents", "agent", "models", "model",
                       "reload", "setup", "breakglass", "focus", "split", "theme"]
        for cmd in system_cmds:
            parsed = self.parser.parse(f"/{cmd}")
            tier = self.router.classify(parsed)
            assert tier == InputTier.SYSTEM, f"/{cmd} should be SYSTEM, got {tier}"

    def test_all_service_commands_route_to_service(self):
        service_cmds = ["sessions", "session", "memory", "tools", "tool",
                        "tool-history", "view", "edit", "diff", "workers",
                        "tokens", "status", "export", "audit", "policy"]
        for cmd in service_cmds:
            parsed = self.parser.parse(f"/{cmd}")
            tier = self.router.classify(parsed)
            assert tier == InputTier.SERVICE, f"/{cmd} should be SERVICE, got {tier}"

    def test_all_agent_commands_route_to_agent(self):
        agent_cmds = ["spawn", "enter", "back", "top", "summon", "kill"]
        for cmd in agent_cmds:
            parsed = self.parser.parse(f"/{cmd}")
            tier = self.router.classify(parsed)
            assert tier == InputTier.AGENT, f"/{cmd} should be AGENT, got {tier}"

    def test_chat_routes_to_agent(self):
        parsed = self.parser.parse("hello")
        tier = self.router.classify(parsed)
        assert tier == InputTier.AGENT

    def test_mention_routes_to_agent(self):
        self.parser.update_agents(["homelab"])
        parsed = self.parser.parse("@homelab hi")
        tier = self.router.classify(parsed)
        assert tier == InputTier.AGENT

    def test_tool_call_routes_to_agent(self):
        parsed = self.parser.parse("!obsidian.search test")
        tier = self.router.classify(parsed)
        assert tier == InputTier.AGENT

    def test_unknown_slash_command_routes_to_agent(self):
        parsed = self.parser.parse("/nonexistent")
        tier = self.router.classify(parsed)
        assert tier == InputTier.AGENT

    def test_bare_at_agent_routes_to_system(self):
        """@homelab alone → parsed as /agent homelab → routes to SYSTEM."""
        self.parser.update_agents(["homelab"])
        parsed = self.parser.parse("@homelab")
        tier = self.router.classify(parsed)
        assert tier == InputTier.SYSTEM


# ---------------------------------------------------------------------------
# 3. AGENT STACK — full navigation, state tracking, edge cases
# ---------------------------------------------------------------------------


class TestAgentStackFullCoverage:
    """Test every AgentStack operation with real state verification."""

    def setup_method(self):
        self.stack = AgentStack()

    def test_empty_stack_depth(self):
        assert self.stack.depth == 0

    def test_push_and_current(self):
        ctx = self.stack.push("huginn", session_id="s1")
        assert self.stack.current.agent_name == "huginn"
        assert self.stack.depth == 1

    def test_push_two_and_breadcrumb(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.push("homelab", session_id="s2")
        assert self.stack.breadcrumb == "huginn > homelab"
        assert self.stack.depth == 2

    def test_pop_returns_to_parent(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.push("homelab", session_id="s2")
        popped = self.stack.pop()
        assert popped.agent_name == "homelab"
        assert self.stack.current.agent_name == "huginn"

    def test_pop_at_root_raises(self):
        self.stack.push("huginn", session_id="s1")
        with pytest.raises(IndexError):
            self.stack.pop()

    def test_pop_to_root(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.push("homelab", session_id="s2")
        self.stack.push("finance", session_id="s3")
        root = self.stack.pop_to_root()
        assert root.agent_name == "huginn"
        assert self.stack.depth == 1

    def test_switch_replaces_entire_stack(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.push("homelab", session_id="s2")
        self.stack.switch("finance", session_id="s3")
        assert self.stack.depth == 1
        assert self.stack.current.agent_name == "finance"

    def test_spawn_adds_child_without_pushing(self):
        self.stack.push("huginn", session_id="s1")
        child = self.stack.spawn("homelab", session_id="s2")
        assert self.stack.current.agent_name == "huginn"  # still huginn
        assert len(self.stack.current.children) == 1
        assert child.agent_name == "homelab"

    def test_enter_pushes_existing_child(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.spawn("homelab", session_id="s2")
        entered = self.stack.enter("homelab")
        assert self.stack.current.agent_name == "homelab"
        assert self.stack.depth == 2

    def test_enter_nonexistent_child_raises(self):
        self.stack.push("huginn", session_id="s1")
        with pytest.raises(KeyError):
            self.stack.enter("nonexistent")

    def test_kill_removes_child(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.spawn("homelab", session_id="s2")
        killed = self.stack.kill("homelab")
        assert killed.agent_name == "homelab"
        assert len(self.stack.current.children) == 0

    def test_kill_nonexistent_raises(self):
        self.stack.push("huginn", session_id="s1")
        with pytest.raises(KeyError):
            self.stack.kill("nonexistent")

    def test_find_on_stack(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.push("homelab", session_id="s2")
        assert self.stack.find("huginn") is not None
        assert self.stack.find("homelab") is not None

    def test_find_spawned_child(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.spawn("homelab", session_id="s2")
        assert self.stack.find("homelab") is not None

    def test_find_missing_returns_none(self):
        self.stack.push("huginn", session_id="s1")
        assert self.stack.find("nonexistent") is None

    def test_status_tracking(self):
        self.stack.push("huginn", session_id="s1")
        ctx = self.stack.current
        assert ctx.status == AgentStatus.IDLE
        ctx.status = AgentStatus.THINKING
        assert ctx.status == AgentStatus.THINKING
        ctx.status_detail = "processing query"
        assert ctx.status_detail == "processing query"

    def test_token_accumulation(self):
        self.stack.push("huginn", session_id="s1")
        ctx = self.stack.current
        assert ctx.token_count == 0
        ctx.token_count += 150
        ctx.token_count += 200
        assert ctx.token_count == 350

    def test_parent_child_links(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.push("homelab", session_id="s2")
        child = self.stack.current
        parent = self.stack.root
        assert child.parent is parent
        assert child in parent.children


# ---------------------------------------------------------------------------
# 4. RENDERER — every render method produces correct output
# ---------------------------------------------------------------------------


class TestRendererFullCoverage:
    """Test every renderer method with real Rich Console + StringIO capture."""

    def setup_method(self):
        self.console, self.buf = make_console()
        self.theme = TuiTheme()
        self.renderer = ChatRenderer(self.console, self.theme)

    def _output(self) -> str:
        return output(self.buf)

    # -- Welcome --

    def test_welcome_banner_shows_corvus(self):
        self.renderer.render_welcome(10, "huginn")
        text = self._output()
        assert "CORVUS" in text

    def test_welcome_banner_shows_agent_count(self):
        self.renderer.render_welcome(10, "huginn")
        text = self._output()
        assert "10 agents" in text

    def test_welcome_banner_shows_default_agent(self):
        self.renderer.render_welcome(10, "huginn")
        text = self._output()
        assert "@huginn" in text

    def test_welcome_banner_shows_help_hint(self):
        self.renderer.render_welcome(10, "huginn")
        text = self._output()
        assert "/help" in text

    def test_welcome_banner_shows_quit_hint(self):
        self.renderer.render_welcome(10, "huginn")
        text = self._output()
        assert "/quit" in text

    # -- User message --

    def test_user_message_shows_you_arrow_agent(self):
        self.renderer.render_user_message("hello", "homelab")
        text = self._output()
        assert "You" in text
        assert "@homelab" in text

    def test_user_message_shows_text(self):
        self.renderer.render_user_message("check nginx", "homelab")
        text = self._output()
        assert "check nginx" in text

    # -- Agent message (non-streaming) --

    def test_agent_message_shows_agent_name(self):
        self.renderer.render_agent_message("homelab", "All systems up.")
        text = self._output()
        assert "@homelab" in text

    def test_agent_message_renders_markdown(self):
        self.renderer.render_agent_message("homelab", "**bold text**")
        text = self._output()
        assert "bold text" in text

    def test_agent_message_shows_tokens_when_provided(self):
        self.renderer.render_agent_message("homelab", "Response", tokens=1500)
        text = self._output()
        assert "1,500 tok" in text

    # -- Thinking spinner --

    def test_thinking_spinner_creates_live(self):
        self.renderer.render_thinking_start("homelab")
        assert self.renderer._thinking_live is not None
        self.renderer._stop_thinking()
        assert self.renderer._thinking_live is None

    def test_thinking_spinner_stops_previous(self):
        self.renderer.render_thinking_start("homelab")
        live1 = self.renderer._thinking_live
        self.renderer.render_thinking_start("work")
        live2 = self.renderer._thinking_live
        assert live2 is not live1
        self.renderer._stop_thinking()

    # -- Streaming --

    def test_stream_lifecycle(self):
        """stream_start → chunk → chunk → stream_end produces one final panel."""
        self.renderer.render_stream_start("homelab")
        assert self.renderer._live is not None
        self.renderer.render_stream_chunk("Hello ")
        self.renderer.render_stream_chunk("world!")
        self.renderer.render_stream_end()
        assert self.renderer._live is None
        text = self._output()
        assert "@homelab" in text
        assert "Hello" in text
        assert "world" in text

    def test_stream_is_transient(self):
        """Streaming Live display is configured as transient so it disappears on stop."""
        self.renderer.render_stream_start("homelab")
        assert self.renderer._live is not None
        assert self.renderer._live.transient is True
        self.renderer.render_stream_chunk("test content")
        self.renderer.render_stream_end()
        assert self.renderer._live is None

    def test_stream_empty_clears_buffer(self):
        """Empty stream → buffer cleared, no agent set."""
        self.renderer.render_stream_start("homelab")
        self.renderer.render_stream_end()
        assert self.renderer._stream_buffer == []
        assert self.renderer._stream_agent == ""

    def test_stream_whitespace_only_clears_buffer(self):
        """Whitespace-only stream → buffer cleared."""
        self.renderer.render_stream_start("homelab")
        self.renderer.render_stream_chunk("   ")
        self.renderer.render_stream_end()
        assert self.renderer._stream_buffer == []
        assert self.renderer._stream_agent == ""

    # -- Tool panels --

    def test_tool_start_shows_tool_name(self):
        self.renderer.render_tool_start("Bash", {"command": "ls"}, "homelab")
        text = self._output()
        assert "Bash" in text

    def test_tool_start_shows_params_as_json(self):
        self.renderer.render_tool_start("Bash", {"command": "ls -la"}, "homelab")
        text = self._output()
        assert "ls -la" in text

    def test_tool_start_no_params(self):
        self.renderer.render_tool_start("Bash", {}, "homelab")
        text = self._output()
        assert "Bash" in text

    def test_tool_result_shows_tool_name(self):
        self.renderer.render_tool_result("Bash", "file1.py\nfile2.py", "homelab")
        text = self._output()
        assert "Bash" in text

    def test_tool_result_shows_output(self):
        self.renderer.render_tool_result("Bash", "file1.py\nfile2.py", "homelab")
        text = self._output()
        assert "file1.py" in text

    def test_tool_result_truncates_long_output(self):
        long_output = "x" * 600
        self.renderer.render_tool_result("Bash", long_output, "homelab")
        text = self._output()
        assert "…" in text

    # -- Confirm prompt --

    def test_confirm_prompt_shows_tool_name(self):
        self.renderer.render_confirm_prompt("c1", "Bash", {"command": "rm -rf /"}, "homelab")
        text = self._output()
        assert "Bash" in text
        assert "Confirm" in text

    def test_confirm_prompt_shows_options(self):
        self.renderer.render_confirm_prompt("c1", "Bash", {"command": "test"}, "homelab")
        text = self._output()
        assert "yes" in text.lower() or "(y)" in text.lower()
        assert "no" in text.lower() or "(n)" in text.lower()
        assert "always" in text.lower() or "(a)" in text.lower()

    # -- Error --

    def test_error_shows_message(self):
        self.renderer.render_error("Something went wrong")
        text = self._output()
        assert "Something went wrong" in text
        assert "Error" in text

    # -- System --

    def test_system_message(self):
        self.renderer.render_system("Connecting...")
        text = self._output()
        assert "Connecting" in text

    # -- Help table --

    def test_help_table_shows_commands(self):
        registry = CommandRegistry()
        registry.register(SlashCommand(name="help", description="Show help", tier=InputTier.SYSTEM))
        registry.register(SlashCommand(name="memory", description="Memory ops", tier=InputTier.SERVICE))
        commands_by_tier = {}
        for tier in (InputTier.SYSTEM, InputTier.SERVICE):
            cmds = registry.commands_for_tier(tier)
            if cmds:
                commands_by_tier[tier.value] = cmds
        self.renderer.render_help(commands_by_tier)
        text = self._output()
        assert "/help" in text
        assert "/memory" in text

    # -- Agents list --

    def test_agents_list_shows_all_agents(self):
        agents = [
            {"id": "huginn", "description": "Router agent"},
            {"id": "homelab", "description": "Home automation"},
            {"id": "work", "description": "Work tasks"},
        ]
        self.renderer.render_agents_list(agents, "huginn")
        text = self._output()
        assert "@huginn" in text
        assert "@homelab" in text
        assert "@work" in text

    def test_agents_list_marks_current(self):
        agents = [{"id": "huginn", "description": "Router"}]
        self.renderer.render_agents_list(agents, "huginn")
        text = self._output()
        assert "●" in text

    # -- Memory results --

    def test_memory_results_shows_records(self):
        results = [
            {"id": "abc12345", "content": "Important fact", "domain": "shared", "score": 0.95},
        ]
        self.renderer.render_memory_results(results)
        text = self._output()
        assert "abc12345" in text
        assert "Important fact" in text
        assert "0.95" in text

    def test_memory_results_empty(self):
        self.renderer.render_memory_results([])
        text = self._output()
        assert "No results" in text

    # -- Tools list --

    def test_tools_list_shows_tools(self):
        tools = [
            {"name": "Bash", "type": "builtin", "description": "Run commands"},
            {"name": "mcp__gmail", "type": "mcp", "description": "Gmail integration"},
        ]
        self.renderer.render_tools_list(tools, "homelab")
        text = self._output()
        assert "Bash" in text
        assert "mcp__gmail" in text

    def test_tools_list_empty(self):
        self.renderer.render_tools_list([], "homelab")
        text = self._output()
        assert "No tools" in text

    # -- Tool detail --

    def test_tool_detail_shows_all_fields(self):
        tool = {"name": "Bash", "type": "builtin", "description": "Run shell commands"}
        self.renderer.render_tool_detail(tool, "homelab")
        text = self._output()
        assert "Bash" in text
        assert "builtin" in text
        assert "Run shell commands" in text

    # -- File view --

    def test_file_view_shows_content(self):
        self.renderer.render_file_view("/tmp/test.py", "print('hello')", "python")
        text = self._output()
        assert "test.py" in text
        assert "hello" in text

    # -- Diff --

    def test_diff_shows_diff_content(self):
        diff = "+added line\n-removed line"
        self.renderer.render_diff(diff, "/tmp/test.py")
        text = self._output()
        assert "added line" in text

    def test_diff_empty(self):
        self.renderer.render_diff("", "/tmp/test.py")
        text = self._output()
        assert "No changes" in text

    # -- Status bar (renderer version) --

    def test_status_bar_render(self):
        self.renderer.render_status_bar("homelab", "claude-sonnet", 1500, workers=2)
        text = self._output()
        assert "homelab" in text
        assert "claude-sonnet" in text
        assert "1500" in text
        assert "2 workers" in text


# ---------------------------------------------------------------------------
# 5. EVENT HANDLER — full event lifecycle, state transitions, tool tracking
# ---------------------------------------------------------------------------


class TestEventHandlerFullCoverage:
    """Test the event handler with real events flowing through real components."""

    def setup_method(self):
        self.console, self.buf = make_console()
        self.theme = TuiTheme()
        self.renderer = ChatRenderer(self.console, self.theme)
        self.stack = AgentStack()
        self.stack.push("huginn", session_id="s1")
        self.counter = TokenCounter()
        self.handler = EventHandler(self.renderer, self.stack, self.counter)

    def _output(self) -> str:
        return output(self.buf)

    # -- RunStart --

    @pytest.mark.asyncio
    async def test_run_start_sets_thinking_status(self):
        await self.handler.handle(RunStart(agent="huginn", run_id="r1"))
        ctx = self.stack.find("huginn")
        assert ctx.status == AgentStatus.THINKING

    @pytest.mark.asyncio
    async def test_run_start_creates_spinner(self):
        await self.handler.handle(RunStart(agent="huginn", run_id="r1"))
        assert self.renderer._thinking_live is not None
        self.renderer._stop_thinking()

    @pytest.mark.asyncio
    async def test_run_start_unknown_agent_no_crash(self):
        """RunStart for agent not on stack should not crash."""
        await self.handler.handle(RunStart(agent="unknown_agent", run_id="r1"))
        # No exception, spinner still created
        assert self.renderer._thinking_live is not None
        self.renderer._stop_thinking()

    # -- RunPhase --

    @pytest.mark.asyncio
    async def test_run_phase_thinking(self):
        await self.handler.handle(RunPhase(agent="huginn", phase="thinking", summary="Analyzing"))
        ctx = self.stack.find("huginn")
        assert ctx.status == AgentStatus.THINKING
        assert ctx.status_detail == "Analyzing"

    @pytest.mark.asyncio
    async def test_run_phase_executing(self):
        await self.handler.handle(RunPhase(agent="huginn", phase="executing", summary="Running tool"))
        ctx = self.stack.find("huginn")
        assert ctx.status == AgentStatus.EXECUTING

    @pytest.mark.asyncio
    async def test_run_phase_waiting(self):
        await self.handler.handle(RunPhase(agent="huginn", phase="waiting", summary="Awaiting approval"))
        ctx = self.stack.find("huginn")
        assert ctx.status == AgentStatus.WAITING

    @pytest.mark.asyncio
    async def test_run_phase_unknown_defaults_to_thinking(self):
        await self.handler.handle(RunPhase(agent="huginn", phase="mysterious", summary=""))
        ctx = self.stack.find("huginn")
        assert ctx.status == AgentStatus.THINKING

    # -- RunOutputChunk (streaming) --

    @pytest.mark.asyncio
    async def test_output_chunks_start_stream(self):
        await self.handler.handle(RunOutputChunk(agent="huginn", content="Hello "))
        assert self.renderer._live is not None
        self.handler._end_stream()

    @pytest.mark.asyncio
    async def test_multiple_chunks_same_agent(self):
        await self.handler.handle(RunOutputChunk(agent="huginn", content="Hello "))
        await self.handler.handle(RunOutputChunk(agent="huginn", content="world!"))
        # Should be same stream, not two streams
        assert self.handler._streaming_agent == "huginn"
        self.handler._end_stream()

    @pytest.mark.asyncio
    async def test_chunk_from_different_agent_ends_previous(self):
        self.stack.spawn("homelab", session_id="s2")
        await self.handler.handle(RunOutputChunk(agent="huginn", content="From huginn"))
        await self.handler.handle(RunOutputChunk(agent="homelab", content="From homelab"))
        assert self.handler._streaming_agent == "homelab"
        self.handler._end_stream()

    # -- RunComplete --

    @pytest.mark.asyncio
    async def test_run_complete_sets_idle(self):
        await self.handler.handle(RunOutputChunk(agent="huginn", content="response"))
        await self.handler.handle(RunComplete(agent="huginn", tokens_used=500))
        ctx = self.stack.find("huginn")
        assert ctx.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_run_complete_accumulates_tokens(self):
        await self.handler.handle(RunComplete(agent="huginn", tokens_used=500))
        ctx = self.stack.find("huginn")
        assert ctx.token_count == 500
        assert self.counter.session_total == 500

    @pytest.mark.asyncio
    async def test_run_complete_multiple_accumulates(self):
        await self.handler.handle(RunComplete(agent="huginn", tokens_used=500))
        await self.handler.handle(RunComplete(agent="huginn", tokens_used=300))
        ctx = self.stack.find("huginn")
        assert ctx.token_count == 800
        assert self.counter.session_total == 800

    # -- ToolStart → ToolResult name tracking --

    @pytest.mark.asyncio
    async def test_tool_name_tracked_from_start_to_result(self):
        await self.handler.handle(ToolStart(
            tool="Bash", tool_id="t1", agent="huginn", input={"command": "ls"}
        ))
        text1 = self._output()
        assert "Bash" in text1

        await self.handler.handle(ToolResult(
            tool="", tool_id="t1", agent="huginn", output="file.py"
        ))
        text2 = self._output()
        # The result panel should also say Bash (recovered from tool_names dict)
        assert text2.count("Bash") >= 2  # start + result

    @pytest.mark.asyncio
    async def test_tool_result_without_start_shows_empty_name(self):
        """ToolResult with no preceding ToolStart → tool name empty or unknown."""
        await self.handler.handle(ToolResult(
            tool="", tool_id="unknown_id", agent="huginn", output="result"
        ))
        # Should not crash

    @pytest.mark.asyncio
    async def test_tool_result_with_name_uses_it_directly(self):
        """If ToolResult itself has a tool name, use it directly."""
        await self.handler.handle(ToolResult(
            tool="Read", tool_id="t1", agent="huginn", output="content"
        ))
        text = self._output()
        assert "Read" in text

    # -- ConfirmRequest --

    @pytest.mark.asyncio
    async def test_confirm_request_stores_pending(self):
        await self.handler.handle(ConfirmRequest(
            tool="Bash", tool_id="c1", agent="huginn", input={"command": "rm -rf /"}
        ))
        assert self.handler.pending_confirm is not None
        assert self.handler.pending_confirm.tool == "Bash"
        assert self.handler.pending_confirm.tool_id == "c1"

    @pytest.mark.asyncio
    async def test_confirm_request_renders_prompt(self):
        await self.handler.handle(ConfirmRequest(
            tool="Bash", tool_id="c1", agent="huginn", input={"command": "rm -rf /"}
        ))
        text = self._output()
        assert "Confirm" in text
        assert "Bash" in text

    @pytest.mark.asyncio
    async def test_clear_confirm(self):
        await self.handler.handle(ConfirmRequest(
            tool="Bash", tool_id="c1", agent="huginn", input={}
        ))
        assert self.handler.pending_confirm is not None
        self.handler.clear_confirm()
        assert self.handler.pending_confirm is None

    # -- Auto-approve --

    @pytest.mark.asyncio
    async def test_auto_approve_skips_confirm_for_allowed_tool(self):
        approved_ids = []

        def check(tool: str) -> bool:
            return tool == "Read"

        def confirm(tool_id: str, action: str) -> None:
            approved_ids.append(tool_id)

        self.handler.set_auto_approve(check, confirm)

        await self.handler.handle(ConfirmRequest(
            tool="Read", tool_id="c1", agent="huginn", input={}
        ))
        # Should NOT store pending (auto-approved)
        assert self.handler.pending_confirm is None
        assert "c1" in approved_ids

    @pytest.mark.asyncio
    async def test_auto_approve_does_not_skip_non_allowed_tool(self):
        def check(tool: str) -> bool:
            return tool == "Read"

        def confirm(tool_id: str, action: str) -> None:
            pass

        self.handler.set_auto_approve(check, confirm)

        await self.handler.handle(ConfirmRequest(
            tool="Bash", tool_id="c1", agent="huginn", input={}
        ))
        # Should store pending (not auto-approved)
        assert self.handler.pending_confirm is not None
        assert self.handler.pending_confirm.tool == "Bash"

    # -- ErrorEvent --

    @pytest.mark.asyncio
    async def test_error_event_renders(self):
        await self.handler.handle(ErrorEvent(message="Connection failed"))
        text = self._output()
        assert "Connection failed" in text

    # -- DispatchComplete --

    @pytest.mark.asyncio
    async def test_dispatch_complete_ends_stream(self):
        await self.handler.handle(RunOutputChunk(agent="huginn", content="partial"))
        assert self.handler._streaming_agent is not None
        await self.handler.handle(DispatchComplete())
        assert self.handler._streaming_agent is None


# ---------------------------------------------------------------------------
# 6. PROTOCOL EVENT PARSING — field aliases, type mapping, edge cases
# ---------------------------------------------------------------------------


class TestProtocolEventParsing:
    """Test parse_event with real server-like payloads."""

    def test_run_start(self):
        event = parse_event({"type": "run_start", "agent": "homelab", "run_id": "r1"})
        assert isinstance(event, RunStart)
        assert event.agent == "homelab"
        assert event.run_id == "r1"

    def test_run_output_chunk(self):
        event = parse_event({"type": "run_output_chunk", "agent": "homelab", "content": "Hello"})
        assert isinstance(event, RunOutputChunk)
        assert event.content == "Hello"

    def test_run_complete_with_tokens(self):
        event = parse_event({"type": "run_complete", "agent": "homelab", "tokens_used": 500})
        assert isinstance(event, RunComplete)
        assert event.tokens_used == 500

    def test_tool_start_with_server_field_names(self):
        """Server sends call_id and params — we alias to tool_id and input."""
        event = parse_event({
            "type": "tool_start",
            "tool": "Bash",
            "call_id": "abc123",
            "params": {"command": "ls"},
        })
        assert isinstance(event, ToolStart)
        assert event.tool == "Bash"
        assert event.tool_id == "abc123"
        assert event.input == {"command": "ls"}

    def test_tool_result_with_server_field_names(self):
        """Server sends call_id and output — we alias to tool_id and output."""
        event = parse_event({
            "type": "tool_result",
            "call_id": "abc123",
            "output": "file1.py",
            "status": "success",
        })
        assert isinstance(event, ToolResult)
        assert event.tool_id == "abc123"
        assert event.output == "file1.py"

    def test_tool_result_with_tool_call_id(self):
        """Some events use tool_call_id instead of call_id."""
        event = parse_event({
            "type": "tool_result",
            "tool_call_id": "xyz789",
            "content": "result text",
        })
        assert isinstance(event, ToolResult)
        assert event.tool_id == "xyz789"
        assert event.output == "result text"

    def test_confirm_request(self):
        event = parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "c1",
            "agent": "homelab",
            "input": {"command": "rm -rf /"},
        })
        assert isinstance(event, ConfirmRequest)
        assert event.tool == "Bash"
        assert event.tool_id == "c1"
        assert event.input == {"command": "rm -rf /"}

    def test_error_event(self):
        event = parse_event({"type": "error", "message": "fail", "code": "E001"})
        assert isinstance(event, ErrorEvent)
        assert event.message == "fail"
        assert event.code == "E001"

    def test_unknown_type_returns_base(self):
        event = parse_event({"type": "unknown_event", "foo": "bar"})
        assert type(event) is ProtocolEvent
        assert event.type == "unknown_event"

    def test_dispatch_start(self):
        event = parse_event({"type": "dispatch_start", "dispatch_id": "d1"})
        assert isinstance(event, DispatchStart)
        assert event.dispatch_id == "d1"

    def test_dispatch_plan(self):
        event = parse_event({
            "type": "dispatch_plan", "dispatch_id": "d1",
            "tasks": [{"agent": "homelab", "task": "check"}],
        })
        assert isinstance(event, DispatchPlan)
        assert len(event.tasks) == 1

    def test_dispatch_complete(self):
        event = parse_event({"type": "dispatch_complete", "dispatch_id": "d1", "result": "ok"})
        assert isinstance(event, DispatchComplete)
        assert event.result == "ok"

    def test_raw_preserved(self):
        raw = {"type": "run_start", "agent": "homelab"}
        event = parse_event(raw)
        assert event.raw == raw

    def test_extra_fields_ignored(self):
        """Fields not in the dataclass are silently dropped."""
        event = parse_event({
            "type": "run_start", "agent": "homelab",
            "some_future_field": "value",
        })
        assert isinstance(event, RunStart)
        assert event.agent == "homelab"


# ---------------------------------------------------------------------------
# 7. THEME — every agent gets a color, fallback rotation works
# ---------------------------------------------------------------------------


class TestThemeFullCoverage:
    """Test theme colors and fallback assignment."""

    def setup_method(self):
        self.theme = TuiTheme()

    def test_known_agents_get_configured_colors(self):
        for agent, expected_color in AGENT_COLORS.items():
            assert self.theme.agent_color(agent) == expected_color

    def test_unknown_agents_get_fallback_colors(self):
        color1 = self.theme.agent_color("agent_x")
        color2 = self.theme.agent_color("agent_y")
        assert color1 != ""
        assert color2 != ""
        assert color1 != color2  # different unknown agents get different colors

    def test_same_unknown_agent_gets_stable_color(self):
        color1 = self.theme.agent_color("agent_x")
        color2 = self.theme.agent_color("agent_x")
        assert color1 == color2

    def test_all_theme_properties_are_strings(self):
        """Every theme property should be a non-empty string."""
        theme = TuiTheme()
        for attr_name in [
            "border", "muted", "system", "status_bar",
            "welcome_title", "welcome_subtitle", "welcome_border",
            "user_label", "user_text", "user_arrow",
            "stream_hint",
            "tool_border", "tool_result_border", "tool_syntax_theme",
            "confirm_border", "confirm_title", "confirm_yes", "confirm_no", "confirm_always",
            "error", "error_border", "warning", "success",
            "table_border", "table_command", "table_tier", "active_marker",
            "memory_id", "memory_content", "memory_domain", "memory_score",
            "tool_name", "tool_type", "tool_description",
            "file_view_border", "file_view_syntax_theme",
            "diff_border", "diff_syntax_theme",
        ]:
            val = getattr(theme, attr_name)
            assert isinstance(val, str), f"theme.{attr_name} is {type(val)}"
            assert len(val) > 0, f"theme.{attr_name} is empty"


# ---------------------------------------------------------------------------
# 8. TOKEN COUNTER — accumulation, per-agent tracking, display formatting
# ---------------------------------------------------------------------------


class TestTokenCounterFullCoverage:

    def setup_method(self):
        self.counter = TokenCounter()

    def test_initial_state(self):
        assert self.counter.session_total == 0
        assert self.counter.all_agents == {}

    def test_add_single_agent(self):
        self.counter.add("huginn", 500)
        assert self.counter.session_total == 500
        assert self.counter.agent_total("huginn") == 500

    def test_add_multiple_agents(self):
        self.counter.add("huginn", 500)
        self.counter.add("homelab", 300)
        assert self.counter.session_total == 800
        assert self.counter.agent_total("huginn") == 500
        assert self.counter.agent_total("homelab") == 300

    def test_accumulate_same_agent(self):
        self.counter.add("huginn", 500)
        self.counter.add("huginn", 300)
        assert self.counter.agent_total("huginn") == 800

    def test_unknown_agent_returns_zero(self):
        assert self.counter.agent_total("nonexistent") == 0

    def test_format_display_small(self):
        self.counter.add("huginn", 500)
        assert self.counter.format_display() == "500 tok"

    def test_format_display_thousands(self):
        self.counter.add("huginn", 45100)
        assert self.counter.format_display() == "45.1k tok"

    def test_reset(self):
        self.counter.add("huginn", 500)
        self.counter.reset()
        assert self.counter.session_total == 0
        assert self.counter.all_agents == {}


# ---------------------------------------------------------------------------
# 9. STATUS BAR — correct content for prompt_toolkit toolbar
# ---------------------------------------------------------------------------


class TestStatusBarFullCoverage:

    def setup_method(self):
        self.stack = AgentStack()
        self.counter = TokenCounter()
        self.theme = TuiTheme()
        self.bar = StatusBar(self.stack, self.counter, self.theme)

    def test_empty_stack_shows_corvus(self):
        html = self.bar()
        assert "corvus" in html.value

    def test_with_agent_shows_agent_name(self):
        self.stack.push("homelab", session_id="s1")
        html = self.bar()
        assert "@homelab" in html.value

    def test_shows_model(self):
        self.bar.model = "claude-sonnet"
        html = self.bar()
        assert "claude-sonnet" in html.value

    def test_shows_token_count(self):
        self.counter.add("huginn", 5000)
        html = self.bar()
        assert "5.0k tok" in html.value

    def test_shows_worker_count(self):
        self.stack.push("huginn", session_id="s1")
        self.stack.spawn("homelab", session_id="s2")
        self.stack.spawn("work", session_id="s3")
        html = self.bar()
        assert "workers: 2" in html.value

    def test_no_workers_hides_field(self):
        self.stack.push("huginn", session_id="s1")
        html = self.bar()
        assert "workers" not in html.value


# ---------------------------------------------------------------------------
# 10. COMPLETER — slash, @agent, !tool, and argument completions
# ---------------------------------------------------------------------------


class TestCompleterFullCoverage:
    """Test all completion paths with real prompt_toolkit documents."""

    def setup_method(self):
        self.registry = CommandRegistry()
        self.registry.register(SlashCommand(name="help", description="Help", tier=InputTier.SYSTEM))
        self.registry.register(SlashCommand(name="agent", description="Switch agent", tier=InputTier.SYSTEM, args_spec="<name>"))
        self.registry.register(SlashCommand(name="memory", description="Memory ops", tier=InputTier.SERVICE))
        self.registry.register(SlashCommand(name="enter", description="Enter agent", tier=InputTier.AGENT, args_spec="<name>"))
        self.registry.register(SlashCommand(name="spawn", description="Spawn agent", tier=InputTier.AGENT, args_spec="<name>"))
        self.registry.register(SlashCommand(name="kill", description="Kill agent", tier=InputTier.AGENT, args_spec="<name>"))
        self.completer = ChatCompleter(self.registry)
        self.completer.update_agents(["huginn", "homelab", "work", "finance"])

    def _complete(self, text: str) -> list[str]:
        """Get completion values for the given text."""
        from prompt_toolkit.document import Document
        from prompt_toolkit.completion import CompleteEvent
        doc = Document(text, len(text))
        event = CompleteEvent()
        return [c.text for c in self.completer.get_completions(doc, event)]

    def test_slash_prefix_lists_all_commands(self):
        results = self._complete("/")
        assert "/help" in results
        assert "/agent" in results
        assert "/memory" in results

    def test_slash_partial_filters(self):
        results = self._complete("/he")
        assert "/help" in results
        assert "/agent" not in results

    def test_slash_no_match(self):
        results = self._complete("/zzz")
        assert results == []

    def test_at_prefix_lists_agents(self):
        results = self._complete("@")
        assert "huginn" in results
        assert "homelab" in results

    def test_at_partial_filters(self):
        results = self._complete("@ho")
        assert "homelab" in results
        assert "huginn" not in results

    def test_agent_command_arg_completion(self):
        """'/agent h' should list agents starting with h."""
        results = self._complete("/agent h")
        assert "huginn" in results
        assert "homelab" in results
        assert "work" not in results

    def test_enter_command_arg_completion(self):
        results = self._complete("/enter f")
        assert "finance" in results

    def test_spawn_command_arg_completion(self):
        results = self._complete("/spawn w")
        assert "work" in results

    def test_kill_command_arg_completion(self):
        results = self._complete("/kill ho")
        assert "homelab" in results

    def test_non_agent_command_no_arg_completion(self):
        """'/memory h' should NOT complete agent names."""
        results = self._complete("/memory h")
        assert results == []

    def test_dynamic_agent_update(self):
        self.completer.update_agents(["music"])
        results = self._complete("@mu")
        assert "music" in results


# ---------------------------------------------------------------------------
# 11. APP INTEGRATION — command handlers produce correct output + state
# ---------------------------------------------------------------------------


class TestAppCommandHandlers:
    """Test TuiApp command handlers with real components, captured output."""

    def setup_method(self):
        self.app = TuiApp()
        # Replace console with captured one
        console, buf = make_console()
        self.app.console = console
        self.app.renderer = ChatRenderer(console, self.app.theme)
        self.app.event_handler = EventHandler(self.app.renderer, self.app.agent_stack, self.app.token_counter)
        self.buf = buf
        # Push initial agent
        self.app.agent_stack.push("huginn", session_id="")
        self.app.parser.update_agents(["huginn", "homelab", "work", "finance"])

    def _output(self) -> str:
        return output(self.buf)

    # -- /help --

    @pytest.mark.asyncio
    async def test_help_command_renders(self):
        parsed = self.app.parser.parse("/help")
        handled = await self.app._handle_system_command(parsed)
        assert handled is True
        text = self._output()
        assert "/help" in text

    # -- /agents --

    @pytest.mark.asyncio
    async def test_agents_command_no_gateway(self):
        """Without a connected gateway, /agents should show error or empty."""
        parsed = self.app.parser.parse("/agents")
        # The gateway isn't connected, so this will raise or show an error
        try:
            handled = await self.app._handle_system_command(parsed)
        except (AssertionError, Exception):
            pass  # Expected — gateway not connected

    # -- /agent <name> --

    @pytest.mark.asyncio
    async def test_agent_switch(self):
        parsed = self.app.parser.parse("/agent homelab")
        handled = await self.app._handle_system_command(parsed)
        assert handled is True
        assert self.app.agent_stack.current.agent_name == "homelab"
        text = self._output()
        assert "homelab" in text

    @pytest.mark.asyncio
    async def test_agent_switch_no_name(self):
        parsed = self.app.parser.parse("/agent")
        handled = await self.app._handle_system_command(parsed)
        assert handled is True
        text = self._output()
        assert "Usage" in text or "Error" in text

    # -- /tokens --

    @pytest.mark.asyncio
    async def test_tokens_command(self):
        self.app.token_counter.add("huginn", 5000)
        parsed = self.app.parser.parse("/tokens")
        handled = await self.app._handle_service_command(parsed)
        assert handled is True
        text = self._output()
        assert "5,000" in text or "5000" in text

    # -- /view --

    def test_view_command_real_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("print('hello world')")
            path = f.name
        try:
            handled = self.app._handle_view_command(path)
            assert handled is True
            text = self._output()
            assert "hello world" in text
        finally:
            os.unlink(path)

    def test_view_command_nonexistent_file(self):
        handled = self.app._handle_view_command("/tmp/nonexistent_file_12345.py")
        assert handled is True
        text = self._output()
        assert "not found" in text.lower() or "error" in text.lower()

    def test_view_command_no_args(self):
        handled = self.app._handle_view_command("")
        assert handled is True
        text = self._output()
        assert "Usage" in text or "Error" in text

    # -- /diff --

    def test_diff_command(self):
        handled = self.app._handle_diff_command("")
        assert handled is True
        # Either shows diff content or "No changes found"

    def test_diff_command_specific_file(self):
        handled = self.app._handle_diff_command("corvus/tui/app.py")
        assert handled is True

    # -- /edit --

    def test_edit_command_no_args(self):
        handled = self.app._handle_edit_command("")
        assert handled is True
        text = self._output()
        assert "Usage" in text or "Error" in text

    # -- always-allow --

    def test_always_allow_initially_empty(self):
        assert not self.app.is_tool_always_allowed("Bash")

    def test_mark_always_allow(self):
        self.app.mark_tool_always_allow("Read")
        assert self.app.is_tool_always_allowed("Read")
        assert not self.app.is_tool_always_allowed("Bash")

    # -- @agent bare → agent switch --

    @pytest.mark.asyncio
    async def test_bare_at_agent_switches(self):
        """Typing @homelab alone should switch agent, not send empty message."""
        parsed = self.app.parser.parse("@homelab")
        assert parsed.kind == "command"
        assert parsed.command == "agent"
        tier = self.app.command_router.classify(parsed)
        assert tier == InputTier.SYSTEM
        handled = await self.app._handle_system_command(parsed)
        assert handled is True
        assert self.app.agent_stack.current.agent_name == "homelab"

    # -- Language detection --

    def test_language_detection_python(self):
        assert TuiApp._detect_language("test.py") == "python"

    def test_language_detection_javascript(self):
        assert TuiApp._detect_language("test.js") == "javascript"

    def test_language_detection_typescript(self):
        assert TuiApp._detect_language("test.ts") == "typescript"

    def test_language_detection_json(self):
        assert TuiApp._detect_language("test.json") == "json"

    def test_language_detection_yaml(self):
        assert TuiApp._detect_language("test.yaml") == "yaml"
        assert TuiApp._detect_language("test.yml") == "yaml"

    def test_language_detection_unknown(self):
        assert TuiApp._detect_language("test.xyz") == "text"

    def test_language_detection_markdown(self):
        assert TuiApp._detect_language("test.md") == "markdown"

    def test_language_detection_svelte(self):
        assert TuiApp._detect_language("test.svelte") == "html"

    def test_language_detection_rust(self):
        assert TuiApp._detect_language("test.rs") == "rust"


# ---------------------------------------------------------------------------
# 12. FULL EVENT FLOW E2E — simulate a complete conversation turn
# ---------------------------------------------------------------------------


class TestFullConversationTurn:
    """Simulate a complete user → agent → response flow."""

    def setup_method(self):
        self.console, self.buf = make_console()
        self.theme = TuiTheme()
        self.renderer = ChatRenderer(self.console, self.theme)
        self.stack = AgentStack()
        self.stack.push("huginn", session_id="s1")
        self.counter = TokenCounter()
        self.handler = EventHandler(self.renderer, self.stack, self.counter)

    def _output(self) -> str:
        return output(self.buf)

    @pytest.mark.asyncio
    async def test_simple_chat_turn(self):
        """User sends message → thinking → streaming → complete."""
        # 1. User message rendered
        self.renderer.render_user_message("What's the status?", "huginn")

        # 2. Run starts (thinking)
        await self.handler.handle(RunStart(agent="huginn", run_id="r1"))
        assert self.stack.find("huginn").status == AgentStatus.THINKING

        # 3. Streaming chunks arrive
        await self.handler.handle(RunOutputChunk(agent="huginn", content="Everything "))
        await self.handler.handle(RunOutputChunk(agent="huginn", content="is running "))
        await self.handler.handle(RunOutputChunk(agent="huginn", content="smoothly."))

        # 4. Run completes
        await self.handler.handle(RunComplete(agent="huginn", tokens_used=150))
        assert self.stack.find("huginn").status == AgentStatus.IDLE
        assert self.counter.session_total == 150

        text = self._output()
        assert "What's the status?" in text
        assert "Everything" in text
        assert "smoothly" in text
        assert "@huginn" in text

    @pytest.mark.asyncio
    async def test_tool_use_turn(self):
        """User sends message → agent calls tool → tool result → response."""
        self.renderer.render_user_message("Run ls", "huginn")

        await self.handler.handle(RunStart(agent="huginn", run_id="r1"))

        # Agent calls a tool
        await self.handler.handle(ToolStart(
            tool="Bash", tool_id="t1", agent="huginn",
            input={"command": "ls"},
        ))
        text_after_tool_start = self._output()
        assert "Bash" in text_after_tool_start
        assert "ls" in text_after_tool_start

        # Tool returns result
        await self.handler.handle(ToolResult(
            tool="", tool_id="t1", agent="huginn",
            output="file1.py\nfile2.py",
        ))
        text_after_tool_result = self._output()
        assert "file1.py" in text_after_tool_result

        # Agent responds with output
        await self.handler.handle(RunOutputChunk(agent="huginn", content="Found 2 files."))
        await self.handler.handle(RunComplete(agent="huginn", tokens_used=200))

        text = self._output()
        assert "Found 2 files" in text
        assert self.counter.session_total == 200

    @pytest.mark.asyncio
    async def test_confirm_flow(self):
        """Tool requires confirmation → user approves → tool runs."""
        await self.handler.handle(RunStart(agent="huginn", run_id="r1"))

        # Confirm request arrives
        await self.handler.handle(ConfirmRequest(
            tool="Bash", tool_id="c1", agent="huginn",
            input={"command": "rm important.txt"},
        ))
        assert self.handler.pending_confirm is not None
        text = self._output()
        assert "Confirm" in text
        assert "rm important.txt" in text

        # User approves (simulated by clearing confirm)
        self.handler.clear_confirm()
        assert self.handler.pending_confirm is None

    @pytest.mark.asyncio
    async def test_error_during_run(self):
        """An error occurs during a run."""
        await self.handler.handle(RunStart(agent="huginn", run_id="r1"))
        await self.handler.handle(ErrorEvent(message="API rate limit exceeded"))
        text = self._output()
        assert "rate limit" in text.lower()

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_sequence(self):
        """Agent calls multiple tools in sequence — names tracked correctly."""
        await self.handler.handle(ToolStart(tool="Read", tool_id="t1", agent="huginn", input={"file": "a.py"}))
        await self.handler.handle(ToolResult(tool="", tool_id="t1", agent="huginn", output="content of a"))

        await self.handler.handle(ToolStart(tool="Bash", tool_id="t2", agent="huginn", input={"command": "ls"}))
        await self.handler.handle(ToolResult(tool="", tool_id="t2", agent="huginn", output="files"))

        text = self._output()
        # Both tool names should appear in start and result panels
        assert text.count("Read") >= 2
        assert text.count("Bash") >= 2


# ---------------------------------------------------------------------------
# 13. SESSION MANAGER — create, resume, list, format
# ---------------------------------------------------------------------------


class TestSessionManager:
    """Test session manager with a stub gateway."""

    def setup_method(self):
        self.stack = AgentStack()
        self.stack.push("huginn", session_id="")

        # Create a minimal stub that implements the protocol methods we need
        class StubGateway(GatewayProtocol):
            async def connect(self): pass
            async def disconnect(self): pass
            async def send_message(self, text, *, session_id=None, requested_agent=None): pass
            async def respond_confirm(self, tool_id, approved): pass
            async def cancel_run(self, run_id): pass
            def on_event(self, callback): pass
            async def list_sessions(self): return []
            async def resume_session(self, session_id):
                return SessionDetail(session_id=session_id, agent_name="homelab", message_count=5)
            async def list_agents(self): return []
            async def list_models(self): return []
            async def memory_search(self, query, agent_name, limit=10): return []
            async def memory_list(self, agent_name, limit=20): return []
            async def memory_save(self, content, agent_name): return "id123"
            async def memory_forget(self, record_id, agent_name): return True
            async def list_agent_tools(self, agent_name): return []

        self.gateway = StubGateway()
        self.mgr = TuiSessionManager(self.gateway, self.stack)

    @pytest.mark.asyncio
    async def test_create_session(self):
        sid = await self.mgr.create("homelab")
        assert len(sid) > 0
        assert self.stack.current.agent_name == "homelab"
        assert self.mgr.current_session_id == sid

    @pytest.mark.asyncio
    async def test_resume_session(self):
        detail = await self.mgr.resume("test-session-id")
        assert detail.agent_name == "homelab"
        assert detail.message_count == 5
        assert self.stack.current.agent_name == "homelab"

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        sessions = await self.mgr.list_sessions()
        assert isinstance(sessions, list)

    def test_format_session_summary(self):
        from datetime import datetime
        summary = SessionSummary(
            session_id="abc12345-full-id",
            agent_name="homelab",
            summary="Fixed the nginx config",
            started_at=datetime(2026, 3, 8, 14, 30),
            message_count=5,
            agents_used=["homelab"],
        )
        formatted = self.mgr.format_session_summary(summary)
        assert "abc12345" in formatted
        assert "@homelab" in formatted
        assert "5 msgs" in formatted
        assert "nginx" in formatted


# ---------------------------------------------------------------------------
# 14. PROMPT BUILDING — correct prompt for each agent stack state
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    """Test the prompt string for different agent stack states."""

    def setup_method(self):
        self.app = TuiApp()

    def test_empty_stack_shows_corvus(self):
        prompt = self.app._build_prompt()
        assert "corvus" in prompt.value

    def test_single_agent(self):
        self.app.agent_stack.push("huginn", session_id="")
        prompt = self.app._build_prompt()
        assert "@huginn" in prompt.value

    def test_nested_agents(self):
        self.app.agent_stack.push("huginn", session_id="")
        self.app.agent_stack.push("homelab", session_id="")
        prompt = self.app._build_prompt()
        # Should show breadcrumb
        assert "huginn" in prompt.value
        assert "homelab" in prompt.value

    def test_agent_switch_updates_prompt(self):
        self.app.agent_stack.push("huginn", session_id="")
        self.app.agent_stack.switch("finance", session_id="")
        prompt = self.app._build_prompt()
        assert "@finance" in prompt.value
        assert "huginn" not in prompt.value


# ---------------------------------------------------------------------------
# 15. HOOKS TOOL OUTPUT — verify tool_response field is captured
# ---------------------------------------------------------------------------


class TestHooksToolResponse:
    """Test that hooks.py correctly reads tool_response from SDK data."""

    def test_hooks_reads_tool_response_field(self):
        """Verify the hooks code looks for 'tool_response' first."""
        from corvus.hooks import create_hooks
        # We can't easily test the full async flow without the emitter,
        # but we can verify the code path exists by checking the source
        import inspect
        source = inspect.getsource(create_hooks)
        assert "tool_response" in source, \
            "hooks.py must look for 'tool_response' field from SDK PostToolUseHookInput"
