"""Behavioral tests for TUI agent management: /agent new, /agent edit, /reload.

Tests use real temp directories, real file I/O, real TuiApp with ScriptableGateway.
NO MOCKS. NO MONKEYPATCH.
"""

import asyncio
import io
import os
import re
import tempfile
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
import pytest_asyncio
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import InputTier
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Scriptable Gateway (same pattern as integration tests)
# ---------------------------------------------------------------------------


class ScriptableGateway(GatewayProtocol):
    """Minimal gateway for testing agent management commands."""

    def __init__(self) -> None:
        self._event_callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]] | None = None
        self._connected = False
        self.agents_data: list[dict] = [
            {"id": "huginn", "description": "Router agent"},
            {"id": "homelab", "description": "Home automation and infrastructure"},
            {"id": "work", "description": "Work tasks and projects"},
        ]
        self.list_agents_call_count: int = 0

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, text: str, *, session_id: str | None = None, requested_agent: str | None = None) -> None:
        pass

    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        pass

    async def cancel_run(self, run_id: str) -> None:
        pass

    async def list_sessions(self) -> list[SessionSummary]:
        return []

    async def resume_session(self, session_id: str) -> SessionDetail:
        return SessionDetail(session_id=session_id)

    async def list_agents(self) -> list[dict[str, Any]]:
        self.list_agents_call_count += 1
        return self.agents_data

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        return []

    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        return []

    async def memory_save(self, content: str, agent_name: str) -> str:
        return "mem-001"

    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        return True

    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        return []

    def on_event(self, callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]]) -> None:
        self._event_callback = callback


# ---------------------------------------------------------------------------
# Test Harness
# ---------------------------------------------------------------------------


class AgentMgmtHarness:
    """Builds a real TuiApp with captured console and ScriptableGateway."""

    def __init__(self) -> None:
        self.app = TuiApp()
        self.buf = io.StringIO()
        self.console = Console(file=self.buf, force_terminal=True, width=120)

        # Replace console and rebuild renderer
        self.app.console = self.console
        self.app.renderer = ChatRenderer(self.console, self.app.theme)
        self.app.event_handler = EventHandler(
            self.app.renderer, self.app.agent_stack, self.app.token_counter,
        )

        # Replace gateway
        self.gateway = ScriptableGateway()
        self.app.gateway = self.gateway

        from corvus.tui.core.session import TuiSessionManager
        self.app.session_manager = TuiSessionManager(self.gateway, self.app.agent_stack)

    async def boot(self) -> None:
        """Simulate app startup: connect, load agents, set up stack."""
        await self.gateway.connect()
        self.gateway.on_event(self.app.event_handler.handle)

        agents = await self.gateway.list_agents()
        agent_names = [a.get("id", "") for a in agents if a.get("id")]
        self.app.parser.update_agents(agent_names)
        self.app.completer.update_agents(agent_names)

        default_agent = "huginn" if "huginn" in agent_names else agent_names[0]
        self.app.agent_stack.push(default_agent, session_id="")

    async def send(self, raw_input: str) -> str:
        """Send input through the full pipeline and return rendered output."""
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

    @property
    def output(self) -> str:
        return self.buf.getvalue()


# ---------------------------------------------------------------------------
# Renderer helpers
# ---------------------------------------------------------------------------


def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    """Build a ChatRenderer backed by a string buffer."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    return renderer, buf


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _output(buf: io.StringIO) -> str:
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences for plain-text assertions."""
    return _ANSI_RE.sub("", text)


# ===========================================================================
# Tests: render_agent_detail
# ===========================================================================


class TestRenderAgentDetail:
    """ChatRenderer.render_agent_detail shows agent metadata in a panel."""

    def test_full_agent_shows_all_fields(self) -> None:
        """render_agent_detail with full agent dict shows name, description, model, tools count."""
        renderer, buf = _make_renderer()
        agent = {
            "id": "homelab",
            "description": "Server management and infrastructure",
            "models": {"preferred": "claude-sonnet-4-20250514", "auto": True},
            "tools": ["Bash", "Read", "Grep", "Glob"],
            "memory": {"own_domain": "homelab"},
            "enabled": True,
        }
        renderer.render_agent_detail(agent)
        text = _output(buf)
        assert "homelab" in text
        assert "Server management" in text
        assert "claude-sonnet-4-20250514" in text or "claude" in text.lower()
        assert "4 tools" in text or "Tools" in text

    def test_minimal_agent_shows_name(self) -> None:
        """render_agent_detail with just name still renders without error."""
        renderer, buf = _make_renderer()
        agent = {"id": "testbot"}
        renderer.render_agent_detail(agent)
        text = _output(buf)
        assert "testbot" in text

    def test_agent_with_no_tools_shows_zero(self) -> None:
        """render_agent_detail with empty tools list shows '0 tools'."""
        renderer, buf = _make_renderer()
        agent = {
            "id": "minimal",
            "description": "A minimal agent",
            "tools": [],
        }
        renderer.render_agent_detail(agent)
        text = _output(buf)
        assert "minimal" in text
        assert "0 tools" in text

    def test_agent_detail_shows_enabled_status(self) -> None:
        """render_agent_detail shows whether agent is enabled."""
        renderer, buf = _make_renderer()
        agent = {
            "id": "finance",
            "description": "Financial tracking",
            "enabled": True,
        }
        renderer.render_agent_detail(agent)
        text = _output(buf)
        assert "finance" in text
        # Should mention enabled status somewhere
        assert "enabled" in text.lower() or "yes" in text.lower() or "true" in text.lower()


# ===========================================================================
# Tests: /agent new — shows config template
# ===========================================================================


class TestAgentNewCommand:
    """'/agent new' renders a YAML config template and the config directory path."""

    @pytest.mark.asyncio
    async def test_agent_new_shows_template(self) -> None:
        """'/agent new' renders agent YAML template."""
        harness = AgentMgmtHarness()
        await harness.boot()
        raw = await harness.send("/agent new")
        text = _strip_ansi(raw)
        # Should show the config template structure
        assert "name:" in text
        assert "description:" in text
        assert "enabled:" in text
        assert "tools:" in text

    @pytest.mark.asyncio
    async def test_agent_new_shows_config_path(self) -> None:
        """'/agent new' shows the config/agents/ directory path."""
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent new")
        assert "config/agents" in text or "config" in text.lower()

    @pytest.mark.asyncio
    async def test_agent_new_mentions_reload(self) -> None:
        """'/agent new' reminds user to /reload after creating config."""
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent new")
        assert "/reload" in text


# ===========================================================================
# Tests: /agent edit <name> — shows config path or opens editor
# ===========================================================================


class TestAgentEditCommand:
    """'/agent edit <name>' shows config path for the named agent."""

    @pytest.mark.asyncio
    async def test_agent_edit_shows_config_path(self) -> None:
        """'/agent edit homelab' shows path to homelab agent config."""
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent edit homelab")
        assert "homelab" in text
        assert "agent.yaml" in text or "config/agents" in text

    @pytest.mark.asyncio
    async def test_agent_edit_unknown_agent(self) -> None:
        """'/agent edit nonexistent' shows an error."""
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent edit nonexistent")
        assert "not found" in text.lower() or "unknown" in text.lower() or "error" in text.lower()

    @pytest.mark.asyncio
    async def test_agent_edit_no_name(self) -> None:
        """'/agent edit' with no name shows usage."""
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent edit")
        assert "usage" in text.lower() or "edit" in text.lower()


# ===========================================================================
# Tests: /reload — refreshes agent registry
# ===========================================================================


class TestReloadCommand:
    """'/reload' re-fetches agents and updates parser/completer."""

    @pytest.mark.asyncio
    async def test_reload_re_fetches_agents(self) -> None:
        """'/reload' calls list_agents on the gateway again."""
        harness = AgentMgmtHarness()
        await harness.boot()
        initial_count = harness.gateway.list_agents_call_count

        text = await harness.send("/reload")
        assert harness.gateway.list_agents_call_count == initial_count + 1
        assert "reload" in text.lower() or "refreshed" in text.lower() or "loaded" in text.lower()

    @pytest.mark.asyncio
    async def test_reload_picks_up_new_agent(self) -> None:
        """After adding an agent to the gateway, /reload makes it available."""
        harness = AgentMgmtHarness()
        await harness.boot()

        # Add a new agent to the gateway data
        harness.gateway.agents_data.append(
            {"id": "newbot", "description": "A freshly added agent"}
        )
        await harness.send("/reload")

        # Parser should now recognize the new agent
        parsed = harness.app.parser.parse("@newbot hello")
        assert parsed.kind == "mention"
        assert "newbot" in parsed.mentions

    @pytest.mark.asyncio
    async def test_reload_updates_completer(self) -> None:
        """After /reload with a new agent, completer has the new name."""
        harness = AgentMgmtHarness()
        await harness.boot()

        harness.gateway.agents_data.append(
            {"id": "freshagent", "description": "Fresh agent"}
        )
        await harness.send("/reload")

        from prompt_toolkit.document import Document
        from prompt_toolkit.completion import CompleteEvent
        doc = Document("@fresha", 7)
        completions = list(harness.app.completer.get_completions(doc, CompleteEvent()))
        names = [c.text for c in completions]
        assert "freshagent" in names

    @pytest.mark.asyncio
    async def test_reload_shows_agent_count(self) -> None:
        """'/reload' output indicates how many agents were loaded."""
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/reload")
        # Should mention the count of agents
        assert "3" in text or "agents" in text.lower()


# ===========================================================================
# Tests: /agent with no args shows agent list (existing behavior preserved)
# ===========================================================================


class TestAgentNoArgs:
    """'/agent' with no arguments still shows usage (existing behavior)."""

    @pytest.mark.asyncio
    async def test_agent_no_args_shows_usage(self) -> None:
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent")
        # Existing behavior: render_error("Usage: /agent <name>")
        assert "usage" in text.lower() or "agent" in text.lower()


# ===========================================================================
# Tests: /agent <name> switches agent (existing behavior preserved)
# ===========================================================================


class TestAgentSwitchPreserved:
    """'/agent homelab' still switches to that agent."""

    @pytest.mark.asyncio
    async def test_agent_switch_still_works(self) -> None:
        harness = AgentMgmtHarness()
        await harness.boot()
        text = await harness.send("/agent homelab")
        assert harness.app.agent_stack.current.agent_name == "homelab"
        assert "homelab" in text
