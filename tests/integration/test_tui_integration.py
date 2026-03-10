"""Full integration tests for the Corvus TUI.

These tests exercise the REAL pipeline end-to-end:
  input text → parser → router → app handler → gateway → events → event handler → renderer → console output

Uses a ScriptableGateway that fires realistic event sequences when
send_message is called, so every component is exercised with real data
flowing through real code paths.

NO MOCKS. Real TuiApp, real parser, real router, real renderer, real event handler.
The only fake is the gateway transport itself (because we can't call the real LLM).
"""

import asyncio
import os
import tempfile
from collections.abc import Callable, Coroutine
from io import StringIO
from typing import Any

import pytest
import pytest_asyncio
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import InputTier
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event


# ---------------------------------------------------------------------------
# Scriptable Gateway — fires realistic event sequences
# ---------------------------------------------------------------------------


class ScriptableGateway(GatewayProtocol):
    """Gateway that records calls and fires scripted event sequences.

    Usage:
        gw = ScriptableGateway()
        gw.script_chat_response("homelab", "All systems are up.", tokens=200)
        app.gateway = gw
        await app._handle_agent_input(parsed)
        # Now check gw.sent_messages and console output
    """

    def __init__(self) -> None:
        self._event_callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]] | None = None
        self._scripted_events: list[dict] = []
        self.sent_messages: list[dict] = []
        self.confirm_responses: list[dict] = []
        self.cancel_requests: list[str] = []
        self._connected = False

        # Configurable data for queries
        self.agents_data: list[dict] = [
            {"id": "huginn", "description": "Router agent"},
            {"id": "homelab", "description": "Home automation and infrastructure"},
            {"id": "work", "description": "Work tasks and projects"},
            {"id": "finance", "description": "Financial tracking"},
        ]
        self.tools_data: dict[str, list[dict]] = {
            "homelab": [
                {"name": "Bash", "type": "builtin", "description": "Run shell commands"},
                {"name": "Read", "type": "builtin", "description": "Read files"},
                {"name": "mcp__home_assistant", "type": "mcp", "description": "Home Assistant control"},
            ],
            "huginn": [
                {"name": "sessions", "type": "builtin", "description": "Session management"},
            ],
        }
        self.memory_data: list[dict] = [
            {"id": "mem-001", "content": "Homelab runs nginx on port 80", "domain": "homelab", "score": 0.92},
            {"id": "mem-002", "content": "Traefik is the reverse proxy", "domain": "homelab", "score": 0.87},
        ]
        self.sessions_data: list[SessionSummary] = []

    # -- Event scripting --

    def script_chat_response(self, agent: str, text: str, tokens: int = 150) -> None:
        """Script a simple chat response: run_start → chunks → run_complete."""
        self._scripted_events = [
            {"type": "run_start", "agent": agent, "run_id": "r1"},
        ]
        # Split text into realistic chunks
        words = text.split()
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i:i + 3])
            if i > 0:
                chunk = " " + chunk
            self._scripted_events.append({
                "type": "run_output_chunk", "agent": agent, "content": chunk,
            })
        self._scripted_events.append({
            "type": "run_complete", "agent": agent, "run_id": "r1", "tokens_used": tokens,
        })

    def script_tool_use(
        self, agent: str, tool: str, params: dict,
        result: str, response: str, tokens: int = 300,
    ) -> None:
        """Script a tool-use turn: run_start → tool_start → tool_result → output → complete."""
        self._scripted_events = [
            {"type": "run_start", "agent": agent, "run_id": "r1"},
            {"type": "tool_start", "tool": tool, "call_id": "t1", "params": params, "agent": agent},
            {"type": "tool_result", "call_id": "t1", "output": result, "status": "success", "agent": agent},
            {"type": "run_output_chunk", "agent": agent, "content": response},
            {"type": "run_complete", "agent": agent, "run_id": "r1", "tokens_used": tokens},
        ]

    def script_confirm_flow(self, agent: str, tool: str, params: dict) -> None:
        """Script a confirm request (stops at confirm — test handles the response)."""
        self._scripted_events = [
            {"type": "run_start", "agent": agent, "run_id": "r1"},
            {
                "type": "confirm_request", "tool": tool, "tool_id": "c1",
                "agent": agent, "input": params,
            },
        ]

    def script_error(self, message: str) -> None:
        """Script an error event."""
        self._scripted_events = [
            {"type": "error", "message": message, "code": "E001"},
        ]

    def script_multi_tool(self, agent: str) -> None:
        """Script multiple tool calls in sequence."""
        self._scripted_events = [
            {"type": "run_start", "agent": agent, "run_id": "r1"},
            {"type": "tool_start", "tool": "Read", "call_id": "t1", "params": {"file_path": "/etc/hosts"}, "agent": agent},
            {"type": "tool_result", "call_id": "t1", "output": "127.0.0.1 localhost", "status": "success", "agent": agent},
            {"type": "tool_start", "tool": "Bash", "call_id": "t2", "params": {"command": "uptime"}, "agent": agent},
            {"type": "tool_result", "call_id": "t2", "output": "up 42 days", "status": "success", "agent": agent},
            {"type": "run_output_chunk", "agent": agent, "content": "Read hosts file and checked uptime."},
            {"type": "run_complete", "agent": agent, "run_id": "r1", "tokens_used": 400},
        ]

    def script_nothing(self) -> None:
        """Don't fire any events (for testing commands that don't hit the gateway)."""
        self._scripted_events = []

    # -- Protocol implementation --

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, text: str, *, session_id: str | None = None, requested_agent: str | None = None) -> None:
        self.sent_messages.append({
            "text": text,
            "session_id": session_id,
            "requested_agent": requested_agent,
        })
        # Fire scripted events
        if self._event_callback is not None:
            for raw in self._scripted_events:
                event = parse_event(raw)
                await self._event_callback(event)
        self._scripted_events = []

    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        self.confirm_responses.append({"tool_id": tool_id, "approved": approved})

    async def cancel_run(self, run_id: str) -> None:
        self.cancel_requests.append(run_id)

    async def list_sessions(self) -> list[SessionSummary]:
        return self.sessions_data

    async def resume_session(self, session_id: str) -> SessionDetail:
        return SessionDetail(session_id=session_id, agent_name="homelab", message_count=5)

    async def list_agents(self) -> list[dict[str, Any]]:
        return self.agents_data

    async def list_models(self) -> list[dict[str, Any]]:
        return [{"id": "claude-sonnet", "provider": "anthropic"}]

    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        return [m for m in self.memory_data if query.lower() in m["content"].lower()][:limit]

    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.memory_data[:limit]

    async def memory_save(self, content: str, agent_name: str) -> str:
        new_id = f"mem-{len(self.memory_data) + 1:03d}"
        self.memory_data.append({"id": new_id, "content": content, "domain": agent_name, "score": 1.0})
        return new_id

    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        before = len(self.memory_data)
        self.memory_data = [m for m in self.memory_data if m["id"] != record_id]
        return len(self.memory_data) < before

    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        return self.tools_data.get(agent_name, [])

    def on_event(self, callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]]) -> None:
        self._event_callback = callback


# ---------------------------------------------------------------------------
# Test harness — builds a real TuiApp with ScriptableGateway + captured console
# ---------------------------------------------------------------------------


class TuiTestHarness:
    """Wires up a real TuiApp with a ScriptableGateway and captured console."""

    def __init__(self) -> None:
        self.app = TuiApp()
        self.buf = StringIO()
        self.console = Console(file=self.buf, force_terminal=True, width=120)

        # Replace the console and rebuild components that depend on it
        self.app.console = self.console
        self.app.renderer = ChatRenderer(self.console, self.app.theme)
        self.app.event_handler = EventHandler(
            self.app.renderer, self.app.agent_stack, self.app.token_counter,
        )

        # Replace gateway with scriptable one
        self.gateway = ScriptableGateway()
        self.app.gateway = self.gateway
        # Rebuild session_manager to use the new gateway
        from corvus.tui.core.session import TuiSessionManager
        self.app.session_manager = TuiSessionManager(self.gateway, self.app.agent_stack)

    async def boot(self) -> None:
        """Simulate the app startup sequence (connect, load agents, wire events)."""
        await self.gateway.connect()
        self.gateway.on_event(self.app.event_handler.handle)

        # Wire auto-approve
        def _auto_approve_confirm(tool_id: str, _action: str) -> None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.gateway.respond_confirm(tool_id, approved=True))
            except RuntimeError:
                pass

        self.app.event_handler.set_auto_approve(
            check_fn=self.app.is_tool_always_allowed,
            confirm_fn=_auto_approve_confirm,
        )

        # Load agents
        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.app.parser.update_agents(agent_names)
        self.app.completer.update_agents(agent_names)

        default_agent = "huginn" if "huginn" in agent_names else agent_names[0]
        self.app.agent_stack.push(default_agent, session_id="")
        self.app.renderer.render_welcome(len(agent_names), default_agent)

    async def send(self, raw_input: str) -> str:
        """Send input through the full pipeline and return rendered output.

        This exercises: parse → route → handler → gateway → events → render.
        Returns the console output AFTER this input was processed.
        """
        # Clear buffer to isolate this input's output
        self.buf.truncate(0)
        self.buf.seek(0)

        parsed = self.app.parser.parse(raw_input)
        tier = self.app.command_router.classify(parsed)

        # Check pending confirmation first
        pending = self.app.event_handler.pending_confirm
        if pending is not None:
            response = raw_input.strip().lower()
            if response in ("y", "yes"):
                await self.gateway.respond_confirm(pending.tool_id, approved=True)
            elif response in ("n", "no"):
                await self.gateway.respond_confirm(pending.tool_id, approved=False)
            elif response in ("a", "always"):
                await self.gateway.respond_confirm(pending.tool_id, approved=True)
                self.app.mark_tool_always_allow(pending.tool)
            else:
                self.app.renderer.render_error("Please respond with (y)es, (n)o, or (a)lways")
                return self.buf.getvalue()
            self.app.event_handler.clear_confirm()
            return self.buf.getvalue()

        if tier is InputTier.SYSTEM:
            await self.app._handle_system_command(parsed)
        elif tier is InputTier.SERVICE:
            await self.app._handle_service_command(parsed)
        else:
            await self.app._handle_agent_input(parsed)

        return self.buf.getvalue()

    @property
    def output(self) -> str:
        """Full console output since last clear."""
        return self.buf.getvalue()


# ---------------------------------------------------------------------------
# Integration tests — full pipeline, realistic scenarios
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def harness():
    h = TuiTestHarness()
    await h.boot()
    return h


class TestBootSequence:
    """Test the startup sequence produces correct initial state."""

    @pytest.mark.asyncio
    async def test_welcome_banner_on_boot(self):
        h = TuiTestHarness()
        await h.boot()
        text = h.output
        assert "CORVUS" in text
        assert "4 agents" in text
        assert "@huginn" in text

    @pytest.mark.asyncio
    async def test_agents_loaded_into_parser(self):
        h = TuiTestHarness()
        await h.boot()
        # Parser should know about all agents
        p = h.app.parser.parse("@homelab check status")
        assert p.kind == "mention"
        assert "homelab" in p.mentions

    @pytest.mark.asyncio
    async def test_initial_agent_is_huginn(self):
        h = TuiTestHarness()
        await h.boot()
        assert h.app.agent_stack.current.agent_name == "huginn"

    @pytest.mark.asyncio
    async def test_completer_knows_agents(self):
        h = TuiTestHarness()
        await h.boot()
        from prompt_toolkit.document import Document
        from prompt_toolkit.completion import CompleteEvent
        doc = Document("@ho", 3)
        completions = list(h.app.completer.get_completions(doc, CompleteEvent()))
        names = [c.text for c in completions]
        assert "homelab" in names


class TestChatFlow:
    """Test full chat: user input → gateway → events → rendered output."""

    @pytest.mark.asyncio
    async def test_simple_chat_response(self, harness):
        """User sends a message, agent responds with text."""
        harness.gateway.script_chat_response("huginn", "I'm the routing agent. How can I help?")
        text = await harness.send("Who are you?")
        # Should show user message
        assert "Who are you?" in text
        # Should show agent response
        assert "routing agent" in text
        assert "@huginn" in text

    @pytest.mark.asyncio
    async def test_chat_routes_to_selected_agent(self, harness):
        """When user switches agent, messages go to that agent."""
        harness.gateway.script_nothing()
        await harness.send("/agent homelab")
        assert harness.app.agent_stack.current.agent_name == "homelab"

        harness.gateway.script_chat_response("homelab", "Nginx is running on port 80.")
        text = await harness.send("check nginx status")
        # Gateway should receive requested_agent=homelab
        msg = harness.gateway.sent_messages[-1]
        assert msg["requested_agent"] == "homelab"
        # Output should show homelab
        assert "@homelab" in text
        assert "Nginx" in text

    @pytest.mark.asyncio
    async def test_huginn_routes_without_requested_agent(self, harness):
        """When on huginn, messages go without requested_agent (let router decide)."""
        harness.gateway.script_chat_response("huginn", "Routing to the right agent.")
        await harness.send("hello")
        msg = harness.gateway.sent_messages[-1]
        assert msg["requested_agent"] is None

    @pytest.mark.asyncio
    async def test_mention_with_text(self, harness):
        """@homelab check nginx → sends 'check nginx' with requested_agent context."""
        harness.gateway.script_chat_response("homelab", "Status: healthy")
        text = await harness.send("@homelab check nginx")
        # Should render the message and response
        assert "check nginx" in text

    @pytest.mark.asyncio
    async def test_token_counting_after_response(self, harness):
        """Token counter should reflect tokens from the response."""
        harness.gateway.script_chat_response("huginn", "Hello!", tokens=250)
        await harness.send("hi")
        assert harness.app.token_counter.session_total == 250
        assert harness.app.token_counter.agent_total("huginn") == 250

    @pytest.mark.asyncio
    async def test_agent_status_idle_after_response(self, harness):
        """Agent should be IDLE after response completes."""
        harness.gateway.script_chat_response("huginn", "Done.")
        await harness.send("test")
        from corvus.tui.core.agent_stack import AgentStatus
        ctx = harness.app.agent_stack.find("huginn")
        assert ctx.status == AgentStatus.IDLE


class TestToolUseFlow:
    """Test full tool-use scenarios through the pipeline."""

    @pytest.mark.asyncio
    async def test_tool_use_shows_tool_and_result(self, harness):
        """Agent calls a tool → tool panel + result panel + response shown."""
        harness.gateway.script_tool_use(
            agent="huginn", tool="Bash", params={"command": "ls"},
            result="file1.py\nfile2.py", response="Found 2 files in the directory.",
        )
        text = await harness.send("list files")
        assert "Bash" in text  # tool name in panel
        assert "ls" in text  # params shown
        assert "file1.py" in text  # result shown
        assert "Found 2 files" in text  # agent response

    @pytest.mark.asyncio
    async def test_tool_name_carries_through(self, harness):
        """Tool name from tool_start appears in tool_result panel (via _tool_names tracking)."""
        harness.gateway.script_tool_use(
            agent="huginn", tool="Read", params={"file_path": "/tmp/test.py"},
            result="print('hello')", response="File contents shown above.",
        )
        text = await harness.send("show me test.py")
        # "Read" should appear at least twice: in ⚡ start and ✓ result
        assert text.count("Read") >= 2

    @pytest.mark.asyncio
    async def test_multi_tool_sequence(self, harness):
        """Multiple tools called in sequence — each tracked correctly."""
        harness.gateway.script_multi_tool("huginn")
        text = await harness.send("check hosts and uptime")
        assert "Read" in text
        assert "Bash" in text
        assert "localhost" in text
        assert "42 days" in text


class TestConfirmFlow:
    """Test the confirmation prompt → user response flow."""

    @pytest.mark.asyncio
    async def test_confirm_prompt_appears(self, harness):
        """Dangerous tool shows confirm prompt."""
        harness.gateway.script_confirm_flow("huginn", "Bash", {"command": "rm -rf /"})
        text = await harness.send("delete everything")
        assert "Confirm" in text
        assert "Bash" in text
        assert "rm -rf" in text
        assert harness.app.event_handler.pending_confirm is not None

    @pytest.mark.asyncio
    async def test_confirm_yes_approves(self, harness):
        """User types 'y' → tool is approved."""
        harness.gateway.script_confirm_flow("huginn", "Bash", {"command": "rm temp"})
        await harness.send("delete temp")
        assert harness.app.event_handler.pending_confirm is not None

        await harness.send("y")
        assert harness.app.event_handler.pending_confirm is None
        assert {"tool_id": "c1", "approved": True} in harness.gateway.confirm_responses

    @pytest.mark.asyncio
    async def test_confirm_no_denies(self, harness):
        harness.gateway.script_confirm_flow("huginn", "Bash", {"command": "rm temp"})
        await harness.send("delete temp")
        await harness.send("n")
        assert harness.app.event_handler.pending_confirm is None
        assert {"tool_id": "c1", "approved": False} in harness.gateway.confirm_responses

    @pytest.mark.asyncio
    async def test_confirm_always_marks_tool(self, harness):
        """User types 'a' → tool approved AND added to always-allow."""
        harness.gateway.script_confirm_flow("huginn", "Read", {"file_path": "/tmp/x"})
        await harness.send("read file")
        await harness.send("a")
        assert harness.app.is_tool_always_allowed("Read")
        assert {"tool_id": "c1", "approved": True} in harness.gateway.confirm_responses

    @pytest.mark.asyncio
    async def test_confirm_invalid_response(self, harness):
        """Typing something other than y/n/a shows error."""
        harness.gateway.script_confirm_flow("huginn", "Bash", {"command": "rm temp"})
        await harness.send("delete temp")
        text = await harness.send("maybe")
        assert "respond with" in text.lower() or "yes" in text.lower()
        # Confirm should still be pending
        assert harness.app.event_handler.pending_confirm is not None


class TestAgentSwitching:
    """Test agent navigation through the full pipeline."""

    @pytest.mark.asyncio
    async def test_slash_agent_switches(self, harness):
        text = await harness.send("/agent homelab")
        assert harness.app.agent_stack.current.agent_name == "homelab"
        assert "homelab" in text

    @pytest.mark.asyncio
    async def test_bare_at_agent_switches(self, harness):
        """@homelab alone → switches agent, doesn't send empty message."""
        text = await harness.send("@homelab")
        assert harness.app.agent_stack.current.agent_name == "homelab"
        assert "homelab" in text
        # Should NOT have sent a message to the gateway
        assert len(harness.gateway.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_switch_then_chat_routes_correctly(self, harness):
        """Switch to homelab, then chat → message goes to homelab."""
        await harness.send("/agent homelab")
        harness.gateway.script_chat_response("homelab", "All good.")
        await harness.send("status check")
        msg = harness.gateway.sent_messages[-1]
        assert msg["requested_agent"] == "homelab"

    @pytest.mark.asyncio
    async def test_back_to_huginn_routes_correctly(self, harness):
        """Switch to homelab, switch back to huginn → routes without requested_agent."""
        await harness.send("/agent homelab")
        await harness.send("/agent huginn")
        harness.gateway.script_chat_response("huginn", "Back to routing.")
        await harness.send("hello")
        msg = harness.gateway.sent_messages[-1]
        assert msg["requested_agent"] is None


class TestSystemCommands:
    """Test system commands through the full pipeline."""

    @pytest.mark.asyncio
    async def test_help_command(self, harness):
        text = await harness.send("/help")
        assert "/help" in text
        assert "/quit" in text
        assert "/memory" in text
        assert "/agent" in text

    @pytest.mark.asyncio
    async def test_agents_command(self, harness):
        text = await harness.send("/agents")
        assert "@huginn" in text
        assert "@homelab" in text
        assert "@work" in text
        assert "@finance" in text

    @pytest.mark.asyncio
    async def test_tokens_command(self, harness):
        harness.app.token_counter.add("huginn", 1500)
        text = await harness.send("/tokens")
        assert "1,500" in text or "1500" in text


class TestServiceCommands:
    """Test service commands through the full pipeline with real gateway data."""

    @pytest.mark.asyncio
    async def test_tools_command(self, harness):
        await harness.send("/agent homelab")
        text = await harness.send("/tools")
        assert "Bash" in text
        assert "Read" in text
        assert "mcp__home_assistant" in text

    @pytest.mark.asyncio
    async def test_tool_detail(self, harness):
        await harness.send("/agent homelab")
        text = await harness.send("/tool Bash")
        assert "Bash" in text
        assert "builtin" in text

    @pytest.mark.asyncio
    async def test_tool_not_found(self, harness):
        text = await harness.send("/tool nonexistent")
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_memory_search(self, harness):
        text = await harness.send("/memory search nginx")
        assert "nginx" in text.lower()
        assert "mem-001" in text

    @pytest.mark.asyncio
    async def test_memory_search_no_results(self, harness):
        text = await harness.send("/memory search zzzzz")
        assert "No memories found" in text or "No results" in text

    @pytest.mark.asyncio
    async def test_memory_list(self, harness):
        text = await harness.send("/memory list")
        assert "mem-001" in text
        assert "mem-002" in text

    @pytest.mark.asyncio
    async def test_memory_save(self, harness):
        text = await harness.send("/memory save Portainer runs on port 9000")
        assert "saved" in text.lower()

    @pytest.mark.asyncio
    async def test_memory_forget(self, harness):
        text = await harness.send("/memory forget mem-001")
        assert "forgotten" in text.lower()

    @pytest.mark.asyncio
    async def test_memory_no_args(self, harness):
        text = await harness.send("/memory")
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_view_real_file(self, harness):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            path = f.name
        try:
            text = await harness.send(f"/view {path}")
            assert "hello" in text
            assert "world" in text
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_view_missing_file(self, harness):
        text = await harness.send("/view /tmp/does_not_exist_12345.py")
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_diff_command(self, harness):
        text = await harness.send("/diff")
        # Either shows diff or "No changes"
        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_sessions_command(self, harness):
        text = await harness.send("/sessions")
        # Empty list or sessions
        assert "session" in text.lower() or "No sessions" in text


class TestErrorHandling:
    """Test error scenarios through the full pipeline."""

    @pytest.mark.asyncio
    async def test_gateway_error_event(self, harness):
        """Gateway sends an error event → rendered as error panel."""
        harness.gateway.script_error("API rate limit exceeded")
        text = await harness.send("do something")
        assert "rate limit" in text.lower()

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self, harness):
        """Empty input should not reach the gateway."""
        text = await harness.send("")
        assert len(harness.gateway.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_unknown_command_falls_through(self, harness):
        """Unknown /command routes to AGENT tier (gateway receives it)."""
        harness.gateway.script_chat_response("huginn", "I don't understand that command.")
        text = await harness.send("/nonexistent")
        # Unknown commands route to agent tier
        assert len(harness.gateway.sent_messages) > 0


class TestToolCallSyntax:
    """Test !tool call syntax through the full pipeline."""

    @pytest.mark.asyncio
    async def test_bang_tool_sends_to_gateway(self, harness):
        """!tool_name → sends '!tool_name' to gateway."""
        harness.gateway.script_chat_response("huginn", "Tool executed.")
        await harness.send("!obsidian.search test query")
        msg = harness.gateway.sent_messages[-1]
        assert "!obsidian.search" in msg["text"]
        assert "test query" in msg["text"]

    @pytest.mark.asyncio
    async def test_bang_tool_routes_to_correct_agent(self, harness):
        """!tool when on homelab → sends to homelab."""
        await harness.send("/agent homelab")
        harness.gateway.script_chat_response("homelab", "Done.")
        await harness.send("!Bash ls -la")
        msg = harness.gateway.sent_messages[-1]
        assert msg["requested_agent"] == "homelab"


class TestPromptState:
    """Test that the prompt reflects the correct state."""

    @pytest.mark.asyncio
    async def test_initial_prompt_shows_huginn(self, harness):
        prompt = harness.app._build_prompt()
        assert "@huginn" in prompt.value

    @pytest.mark.asyncio
    async def test_prompt_after_switch(self, harness):
        await harness.send("/agent homelab")
        prompt = harness.app._build_prompt()
        assert "@homelab" in prompt.value

    @pytest.mark.asyncio
    async def test_status_bar_after_tokens(self, harness):
        harness.gateway.script_chat_response("huginn", "Hello!", tokens=5000)
        await harness.send("hi")
        bar = harness.app.status_bar()
        assert "5.0k tok" in bar.value
        assert "@huginn" in bar.value


class TestAutoApprove:
    """Test auto-approve integration through the full pipeline."""

    @pytest.mark.asyncio
    async def test_always_allow_skips_confirm(self, harness):
        """After marking a tool always-allow, it shouldn't show confirm prompt."""
        # First time: confirm prompt appears
        harness.gateway.script_confirm_flow("huginn", "Read", {"file_path": "/tmp/x"})
        await harness.send("read file")
        assert harness.app.event_handler.pending_confirm is not None

        # User types 'a' (always)
        await harness.send("a")
        assert harness.app.is_tool_always_allowed("Read")

        # Second time: auto-approved (no pending confirm)
        harness.gateway.script_confirm_flow("huginn", "Read", {"file_path": "/tmp/y"})
        await harness.send("read another file")
        # The auto-approve callback fires and approves immediately
        assert harness.app.event_handler.pending_confirm is None

    @pytest.mark.asyncio
    async def test_always_allow_only_for_that_tool(self, harness):
        """Always-allow for Read doesn't affect Bash."""
        harness.app.mark_tool_always_allow("Read")
        harness.gateway.script_confirm_flow("huginn", "Bash", {"command": "rm temp"})
        await harness.send("delete temp")
        # Bash should still require confirmation
        assert harness.app.event_handler.pending_confirm is not None
        assert harness.app.event_handler.pending_confirm.tool == "Bash"
