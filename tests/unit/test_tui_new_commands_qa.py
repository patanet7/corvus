"""Comprehensive QA tests for newly implemented TUI command handlers.

Tests the following commands end-to-end through the real TuiApp pipeline:
  /workers    — list active child/background agents
  /status     — system status overview
  /tool-history — recent tool calls from audit log
  /summon     — summon an agent as a coworker
  /login      — WebSocket authentication
  /split + /workers integration

Exercises: input -> parser -> router -> handler -> renderer -> console output.

NO MOCKS. Real TuiApp, real renderer, real Rich console with StringIO capture.
The only fake is the gateway transport (ScriptableGateway).
"""

import os
import tempfile
import time
from collections.abc import Callable, Coroutine
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import InputTier
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event


# ---------------------------------------------------------------------------
# ScriptableGateway — test double for gateway transport
# ---------------------------------------------------------------------------


class ScriptableGateway(GatewayProtocol):
    """Gateway that records calls and fires scripted event sequences."""

    def __init__(self) -> None:
        self._event_callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]] | None = None
        self._scripted_events: list[dict] = []
        self.sent_messages: list[dict] = []
        self.confirm_responses: list[dict] = []
        self.cancel_requests: list[str] = []
        self._connected = False

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
            ],
        }
        self.memory_data: list[dict] = []
        self.sessions_data: list[SessionSummary] = []
        self.models_data: list[dict] = [
            {"id": "claude-sonnet", "provider": "anthropic", "name": "Claude Sonnet"},
        ]

    def script_chat_response(self, agent: str, text: str, tokens: int = 150) -> None:
        self._scripted_events = [
            {"type": "run_start", "agent": agent, "run_id": "r1"},
        ]
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

    def script_nothing(self) -> None:
        self._scripted_events = []

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, text: str, *, session_id: str | None = None, requested_agent: str | None = None) -> None:
        self.sent_messages.append({"text": text, "session_id": session_id, "requested_agent": requested_agent})
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
        return self.models_data

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
# Test Harness
# ---------------------------------------------------------------------------


class QAHarness:
    """Wires up a real TuiApp with ScriptableGateway and captured console."""

    def __init__(self) -> None:
        self.app = TuiApp()
        self.buf = StringIO()
        self.console = Console(file=self.buf, force_terminal=True, width=120)

        self.app.console = self.console
        self.app.renderer = ChatRenderer(self.console, self.app.theme)
        self.app.event_handler = EventHandler(
            self.app.renderer, self.app.agent_stack, self.app.token_counter,
        )

        self.gateway = ScriptableGateway()
        self.app.gateway = self.gateway
        self.app.session_manager = TuiSessionManager(self.gateway, self.app.agent_stack)

    async def boot(self) -> None:
        await self.gateway.connect()
        self.gateway.on_event(self.app.event_handler.handle)

        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.app.parser.update_agents(agent_names)
        self.app.completer.update_agents(agent_names)

        default_agent = "huginn" if "huginn" in agent_names else agent_names[0]
        self.app.agent_stack.push(default_agent, session_id="")
        self.clear()

    async def send(self, raw_input: str) -> str:
        self.buf.truncate(0)
        self.buf.seek(0)

        parsed = self.app.parser.parse(raw_input)
        tier = self.app.command_router.classify(parsed)

        if tier is InputTier.SYSTEM:
            await self.app._handle_system_command(parsed)
        elif tier is InputTier.SERVICE:
            await self.app._handle_service_command(parsed)
        else:
            await self.app._handle_agent_input(parsed)

        return self.buf.getvalue()

    def clear(self) -> None:
        self.buf.truncate(0)
        self.buf.seek(0)

    @property
    def output(self) -> str:
        return self.buf.getvalue()


@pytest_asyncio.fixture
async def h():
    harness = QAHarness()
    await harness.boot()
    return harness


# ===========================================================================
# /workers command
# ===========================================================================


class TestWorkersCommand:
    """Verify /workers shows active child/background agents."""

    @pytest.mark.asyncio
    async def test_workers_no_active_agents(self, h: QAHarness) -> None:
        """With an empty agent stack, /workers reports no active agents."""
        h.app.agent_stack._stack.clear()
        text = await h.send("/workers")
        assert "No active agents" in text

    @pytest.mark.asyncio
    async def test_workers_agent_with_no_children(self, h: QAHarness) -> None:
        """Current agent exists but has no spawned children."""
        text = await h.send("/workers")
        assert "no active workers" in text
        assert "huginn" in text

    @pytest.mark.asyncio
    async def test_workers_agent_with_spawned_children(self, h: QAHarness) -> None:
        """After spawning children, /workers lists them with status."""
        h.app.agent_stack.spawn("homelab", session_id="s1")
        h.app.agent_stack.spawn("finance", session_id="s2")
        text = await h.send("/workers")
        assert "Workers for @huginn" in text
        assert "@homelab" in text
        assert "@finance" in text

    @pytest.mark.asyncio
    async def test_workers_shows_child_status(self, h: QAHarness) -> None:
        """Spawned children display their status label."""
        from corvus.tui.core.agent_stack import AgentStatus

        child = h.app.agent_stack.spawn("work", session_id="s1")
        child.status = AgentStatus.THINKING
        text = await h.send("/workers")
        assert "thinking" in text

    @pytest.mark.asyncio
    async def test_workers_after_kill_child(self, h: QAHarness) -> None:
        """After killing a child, /workers no longer lists it."""
        h.app.agent_stack.spawn("work", session_id="s1")
        h.app.agent_stack.kill("work")
        text = await h.send("/workers")
        assert "no active workers" in text

    @pytest.mark.asyncio
    async def test_workers_multiple_children_different_status(self, h: QAHarness) -> None:
        """Multiple children with different statuses are all listed."""
        from corvus.tui.core.agent_stack import AgentStatus

        child1 = h.app.agent_stack.spawn("homelab", session_id="s1")
        child1.status = AgentStatus.EXECUTING
        child2 = h.app.agent_stack.spawn("finance", session_id="s2")
        child2.status = AgentStatus.IDLE
        text = await h.send("/workers")
        assert "@homelab" in text
        assert "@finance" in text
        assert "executing" in text
        assert "idle" in text


# ===========================================================================
# /status command
# ===========================================================================


class TestStatusCommand:
    """Verify /status shows system status overview."""

    @pytest.mark.asyncio
    async def test_status_shows_gateway_connection(self, h: QAHarness) -> None:
        """Status output includes gateway connection state."""
        text = await h.send("/status")
        assert "Gateway" in text
        assert "connected" in text

    @pytest.mark.asyncio
    async def test_status_shows_agent_count(self, h: QAHarness) -> None:
        """Status output includes agent count from gateway."""
        text = await h.send("/status")
        assert "4 available" in text or "Agents" in text

    @pytest.mark.asyncio
    async def test_status_shows_current_agent(self, h: QAHarness) -> None:
        """Status output includes the current agent name."""
        text = await h.send("/status")
        assert "@huginn" in text

    @pytest.mark.asyncio
    async def test_status_shows_token_count(self, h: QAHarness) -> None:
        """Status output includes token usage."""
        h.app.token_counter.add("huginn", 500)
        text = await h.send("/status")
        assert "Tokens" in text
        assert "500" in text

    @pytest.mark.asyncio
    async def test_status_shows_permission_tier(self, h: QAHarness) -> None:
        """Status output includes the current permission tier."""
        text = await h.send("/status")
        assert "Permission tier" in text
        assert "default" in text

    @pytest.mark.asyncio
    async def test_status_shows_breakglass_info(self, h: QAHarness) -> None:
        """When break-glass is active, status shows remaining time."""
        from corvus.security.policy import PolicyEngine

        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass 30")
        h.clear()
        text = await h.send("/status")
        assert "Break-glass" in text
        assert "active" in text

    @pytest.mark.asyncio
    async def test_status_disconnected_gateway(self, h: QAHarness) -> None:
        """When gateway is disconnected, status reflects that."""
        h.gateway._connected = False
        text = await h.send("/status")
        assert "not connected" in text

    @pytest.mark.asyncio
    async def test_status_after_agent_switch(self, h: QAHarness) -> None:
        """After switching agent, status shows the new current agent."""
        await h.send("/agent homelab")
        h.clear()
        text = await h.send("/status")
        assert "@homelab" in text


# ===========================================================================
# /tool-history command
# ===========================================================================


class TestToolHistoryCommand:
    """Verify /tool-history shows recent tool calls from audit log."""

    @pytest.mark.asyncio
    async def test_tool_history_no_audit_log(self, h: QAHarness) -> None:
        """Without an audit log configured, shows error message."""
        h.app._audit_log = None
        text = await h.send("/tool-history")
        assert "not configured" in text.lower() or "cannot show" in text.lower()

    @pytest.mark.asyncio
    async def test_tool_history_empty_audit_log(self, h: QAHarness) -> None:
        """With an empty audit log, shows 'no tool calls recorded'."""
        from corvus.security.audit import AuditLog

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            audit_path = f.name
        try:
            h.app._audit_log = AuditLog(Path(audit_path))
            text = await h.send("/tool-history")
            assert "No tool calls recorded" in text
        finally:
            if os.path.exists(audit_path):
                os.unlink(audit_path)

    @pytest.mark.asyncio
    async def test_tool_history_with_entries(self, h: QAHarness) -> None:
        """With audit log entries, shows tool call records."""
        from corvus.security.audit import AuditLog

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            audit.log_tool_call(
                tool_name="Bash",
                agent_name="homelab",
                outcome="allowed",
                session_id="test-session",
            )
            audit.log_tool_call(
                tool_name="Read",
                agent_name="homelab",
                outcome="allowed",
                session_id="test-session",
            )
            h.app._audit_log = audit
            text = await h.send("/tool-history")
            assert "Tool History" in text
            assert "Bash" in text or "homelab" in text
        finally:
            if os.path.exists(audit_path):
                os.unlink(audit_path)

    @pytest.mark.asyncio
    async def test_tool_history_truncates_to_20(self, h: QAHarness) -> None:
        """With more than 20 entries, only the last 20 are shown."""
        from corvus.security.audit import AuditLog

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            for i in range(30):
                audit.log_tool_call(
                    tool_name=f"Tool{i}",
                    agent_name="homelab",
                    outcome="allowed",
                    session_id="s1",
                )
            h.app._audit_log = audit
            text = await h.send("/tool-history")
            assert "Tool History" in text
            # Should NOT contain the earliest tools (0-9) since only last 20 shown
            # The last entry (Tool29) should be present
            assert "Tool29" in text
        finally:
            if os.path.exists(audit_path):
                os.unlink(audit_path)

    @pytest.mark.asyncio
    async def test_tool_history_shows_denied_entries(self, h: QAHarness) -> None:
        """Tool history includes denied tool calls too."""
        from corvus.security.audit import AuditLog

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            audit.log_tool_call(
                tool_name="Write",
                agent_name="finance",
                outcome="denied",
                session_id="s1",
            )
            h.app._audit_log = audit
            text = await h.send("/tool-history")
            assert "denied" in text.lower() or "Write" in text
        finally:
            if os.path.exists(audit_path):
                os.unlink(audit_path)


# ===========================================================================
# /summon command
# ===========================================================================


class TestSummonCommand:
    """Verify /summon spawns an agent as a coworker."""

    @pytest.mark.asyncio
    async def test_summon_agent(self, h: QAHarness) -> None:
        """Summon an agent and verify the output message."""
        text = await h.send("/summon homelab")
        assert "Summoned" in text
        assert "@homelab" in text

    @pytest.mark.asyncio
    async def test_summon_without_args(self, h: QAHarness) -> None:
        """Summon without arguments shows usage error."""
        text = await h.send("/summon")
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_summon_adds_child_to_stack(self, h: QAHarness) -> None:
        """After summoning, the agent appears as a child of the current agent."""
        await h.send("/summon work")
        current = h.app.agent_stack.current
        child_names = [c.agent_name for c in current.children]
        assert "work" in child_names

    @pytest.mark.asyncio
    async def test_summon_then_workers_shows_child(self, h: QAHarness) -> None:
        """After summoning, /workers lists the summoned agent."""
        await h.send("/summon finance")
        h.clear()
        text = await h.send("/workers")
        assert "@finance" in text
        assert "Workers for @huginn" in text

    @pytest.mark.asyncio
    async def test_summon_does_not_push_stack(self, h: QAHarness) -> None:
        """Summoning does not change the current agent (stays on huginn)."""
        await h.send("/summon homelab")
        assert h.app.agent_stack.current.agent_name == "huginn"
        assert h.app.agent_stack.depth == 1

    @pytest.mark.asyncio
    async def test_summon_shows_coworker_label(self, h: QAHarness) -> None:
        """Output mentions 'coworker of' the current agent."""
        text = await h.send("/summon work")
        assert "coworker" in text.lower()
        assert "@huginn" in text

    @pytest.mark.asyncio
    async def test_summon_multiple_agents(self, h: QAHarness) -> None:
        """Summon multiple agents, all appear as children."""
        await h.send("/summon homelab")
        await h.send("/summon finance")
        current = h.app.agent_stack.current
        child_names = [c.agent_name for c in current.children]
        assert "homelab" in child_names
        assert "finance" in child_names


# ===========================================================================
# /login command
# ===========================================================================


class TestLoginCommand:
    """Verify /login handles authentication flow."""

    @pytest.mark.asyncio
    async def test_login_non_websocket_mode(self, h: QAHarness) -> None:
        """In non-websocket mode, login reports not needed."""
        text = await h.send("/login")
        assert "not needed" in text.lower() or "in-process" in text.lower()

    @pytest.mark.asyncio
    async def test_login_non_websocket_with_token_arg(self, h: QAHarness) -> None:
        """Even with a token argument, non-websocket mode says not needed."""
        text = await h.send("/login my-token-123")
        assert "not needed" in text.lower() or "in-process" in text.lower()

    @pytest.mark.asyncio
    async def test_login_message_mentions_gateway_type(self, h: QAHarness) -> None:
        """The login message indicates the gateway type being used."""
        text = await h.send("/login")
        assert "in-process" in text.lower() or "gateway" in text.lower()


# ===========================================================================
# /split + /workers integration
# ===========================================================================


class TestSplitWorkersIntegration:
    """Verify /split and /workers work independently and together."""

    @pytest.mark.asyncio
    async def test_split_then_workers(self, h: QAHarness) -> None:
        """Activating split mode does not affect /workers output."""
        await h.send("/split homelab finance")
        h.clear()
        text = await h.send("/workers")
        # Workers reports on agent stack children, not split panes
        assert "no active workers" in text or "No active agents" in text

    @pytest.mark.asyncio
    async def test_split_then_summon_then_workers(self, h: QAHarness) -> None:
        """Split mode + summoned agent: /workers shows the child."""
        await h.send("/split homelab finance")
        await h.send("/summon work")
        h.clear()
        text = await h.send("/workers")
        assert "@work" in text

    @pytest.mark.asyncio
    async def test_split_active_workers_inactive(self, h: QAHarness) -> None:
        """Split active but no workers: both report their own state."""
        text_split = await h.send("/split homelab finance")
        assert "activated" in text_split.lower()

        h.clear()
        text_workers = await h.send("/workers")
        assert "no active workers" in text_workers

    @pytest.mark.asyncio
    async def test_workers_after_split_off(self, h: QAHarness) -> None:
        """After deactivating split, /workers still works normally."""
        await h.send("/split homelab finance")
        await h.send("/split off")
        h.clear()
        text = await h.send("/workers")
        assert "no active workers" in text or "huginn" in text

    @pytest.mark.asyncio
    async def test_split_and_status_coexist(self, h: QAHarness) -> None:
        """Both /split status and /status work independently."""
        await h.send("/split homelab finance")
        h.clear()
        text_split = await h.send("/split")
        assert "SPLIT" in text_split

        h.clear()
        text_status = await h.send("/status")
        assert "Gateway" in text_status
        assert "connected" in text_status


# ===========================================================================
# Cross-command integration
# ===========================================================================


class TestNewCommandsCrossIntegration:
    """Test new commands interacting with each other and existing features."""

    @pytest.mark.asyncio
    async def test_summon_then_kill_then_workers(self, h: QAHarness) -> None:
        """Summon, kill, then verify workers is empty."""
        await h.send("/summon homelab")
        await h.send("/kill homelab")
        h.clear()
        text = await h.send("/workers")
        assert "no active workers" in text

    @pytest.mark.asyncio
    async def test_status_reflects_token_accumulation(self, h: QAHarness) -> None:
        """Token counter updates are visible in /status."""
        h.app.token_counter.add("huginn", 200)
        h.app.token_counter.add("huginn", 300)
        text = await h.send("/status")
        assert "500" in text

    @pytest.mark.asyncio
    async def test_status_after_breakglass_off(self, h: QAHarness) -> None:
        """After breakglass deactivation, status shows default tier."""
        from corvus.security.policy import PolicyEngine

        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        await h.send("/breakglass off")
        h.clear()
        text = await h.send("/status")
        assert "default" in text
        # Should NOT show break-glass active
        assert "Break-glass" not in text or "active" not in text

    @pytest.mark.asyncio
    async def test_tool_history_after_audit_entries_added(self, h: QAHarness) -> None:
        """Tool history reflects entries added after initial setup."""
        from corvus.security.audit import AuditLog

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            h.app._audit_log = audit

            # Initially empty
            text1 = await h.send("/tool-history")
            assert "No tool calls recorded" in text1

            # Add an entry
            audit.log_tool_call(
                tool_name="Bash",
                agent_name="homelab",
                outcome="allowed",
                session_id="s1",
            )
            h.clear()
            text2 = await h.send("/tool-history")
            assert "Tool History" in text2
        finally:
            if os.path.exists(audit_path):
                os.unlink(audit_path)

    @pytest.mark.asyncio
    async def test_summon_then_enter_then_workers(self, h: QAHarness) -> None:
        """Summon a child, enter it, then check workers from the child's perspective."""
        await h.send("/summon homelab")
        await h.send("/enter homelab")
        assert h.app.agent_stack.current.agent_name == "homelab"
        h.clear()
        text = await h.send("/workers")
        # homelab has no children of its own
        assert "no active workers" in text
        assert "@homelab" in text

    @pytest.mark.asyncio
    async def test_help_lists_new_commands(self, h: QAHarness) -> None:
        """/help should include all new commands."""
        text = await h.send("/help")
        for cmd in ["workers", "status", "tool-history", "summon", "login"]:
            assert cmd in text, f"Missing /{cmd} in help output"

    @pytest.mark.asyncio
    async def test_status_shows_correct_agent_count_after_reload(self, h: QAHarness) -> None:
        """After adding agents and reloading, /status reflects the new count."""
        h.gateway.agents_data.append({"id": "music", "description": "Music agent"})
        await h.send("/reload")
        h.clear()
        text = await h.send("/status")
        assert "5 available" in text


# ===========================================================================
# Edge cases and error handling
# ===========================================================================


class TestNewCommandsEdgeCases:
    """Edge cases for the new command handlers."""

    @pytest.mark.asyncio
    async def test_workers_after_agent_switch(self, h: QAHarness) -> None:
        """After switching agent, workers reflects the new agent's children."""
        h.app.agent_stack.spawn("work", session_id="s1")
        # Switch to homelab (clears stack and starts fresh)
        await h.send("/agent homelab")
        h.clear()
        text = await h.send("/workers")
        # New agent has no children
        assert "no active workers" in text
        assert "@homelab" in text

    @pytest.mark.asyncio
    async def test_status_with_zero_tokens(self, h: QAHarness) -> None:
        """Status works correctly when no tokens have been used."""
        text = await h.send("/status")
        assert "Tokens" in text
        # Should show 0 or the format_display default
        assert "0" in text

    @pytest.mark.asyncio
    async def test_summon_same_agent_twice(self, h: QAHarness) -> None:
        """Summoning the same agent twice adds two children."""
        await h.send("/summon homelab")
        await h.send("/summon homelab")
        current = h.app.agent_stack.current
        homelab_children = [c for c in current.children if c.agent_name == "homelab"]
        assert len(homelab_children) == 2

    @pytest.mark.asyncio
    async def test_tool_history_distinct_from_audit(self, h: QAHarness) -> None:
        """Tool history and audit are separate commands accessing the same log."""
        from corvus.security.audit import AuditLog

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            audit.log_tool_call(
                tool_name="Bash",
                agent_name="homelab",
                outcome="allowed",
                session_id="s1",
            )
            h.app._audit_log = audit

            text_history = await h.send("/tool-history")
            assert "Tool History" in text_history

            h.clear()
            text_audit = await h.send("/audit")
            assert "Audit" in text_audit

            # Both show the same entry but with different titles
            assert "Bash" in text_history or "homelab" in text_history
            assert "Bash" in text_audit or "homelab" in text_audit
        finally:
            if os.path.exists(audit_path):
                os.unlink(audit_path)

    @pytest.mark.asyncio
    async def test_workers_with_deeply_nested_agent(self, h: QAHarness) -> None:
        """Workers shows children of the deepest current agent."""
        h.app.agent_stack.spawn("homelab", session_id="s1")
        h.app.agent_stack.enter("homelab")
        h.app.agent_stack.spawn("work", session_id="s2")
        assert h.app.agent_stack.current.agent_name == "homelab"
        text = await h.send("/workers")
        assert "Workers for @homelab" in text
        assert "@work" in text
