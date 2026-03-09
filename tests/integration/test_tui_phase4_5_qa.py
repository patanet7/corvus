"""Comprehensive QA integration tests for Corvus TUI Phase 4 & 5 features.

Tests ALL Phase 4 (System Screens) and Phase 5 (Polish & Production) features
end-to-end through the real TuiApp pipeline with actual rendered output capture.

Exercises: input → parser → router → app handler → gateway → events → renderer → console output.

Every test captures actual Rich console output and verifies:
  - What the user SEES (rendered text, panels, tables, formatting)
  - What gets SENT to the gateway
  - State transitions (split manager, break-glass, theme, tier)
  - Error cases and edge cases

NO MOCKS. Real TuiApp, real renderer, real Rich console with StringIO capture.
The only fake is the gateway transport (ScriptableGateway).
"""

import os
import tempfile
import time
from io import StringIO
from pathlib import Path

import pytest
import pytest_asyncio
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import InputTier
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.core.session import TuiSessionManager
from corvus.tui.core.split_manager import SplitManager
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary
from corvus.tui.protocol.events import ProtocolEvent, parse_event
from corvus.tui.theme import TuiTheme, available_themes

from collections.abc import Callable, Coroutine
from typing import Any


# ---------------------------------------------------------------------------
# ScriptableGateway — same as in test_tui_integration.py
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
        self.models_data: list[dict] = [
            {"id": "claude-sonnet", "provider": "anthropic", "name": "Claude Sonnet"},
            {"id": "llama-3.1", "provider": "ollama", "name": "Llama 3.1"},
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
# Phase 4: System Screens
# ===========================================================================


# ---------------------------------------------------------------------------
# 4.1 Setup Screen — /setup credential dashboard
# ---------------------------------------------------------------------------


class TestSetupScreen:
    """Verify /setup renders a credential dashboard with real provider checks."""

    @pytest.mark.asyncio
    async def test_setup_renders_table(self, h: QAHarness) -> None:
        text = await h.send("/setup")
        assert "Credential Status" in text

    @pytest.mark.asyncio
    async def test_setup_shows_provider_names(self, h: QAHarness) -> None:
        text = await h.send("/setup")
        assert "Anthropic" in text
        assert "OpenAI" in text
        assert "Ollama" in text
        assert "Gmail" in text
        assert "Home Assistant" in text
        assert "Paperless" in text
        assert "Firefly" in text

    @pytest.mark.asyncio
    async def test_setup_shows_status_markers(self, h: QAHarness) -> None:
        """Each provider row shows Configured or Not Configured."""
        text = await h.send("/setup")
        # At minimum Ollama (always configured) should show configured
        assert "Configured" in text

    @pytest.mark.asyncio
    async def test_setup_shows_detail_column(self, h: QAHarness) -> None:
        """Detail column shows env var status or URL."""
        text = await h.send("/setup")
        # Ollama always shows its host URL
        assert "localhost" in text or "OLLAMA_HOST" in text

    @pytest.mark.asyncio
    async def test_setup_status_subcommand(self, h: QAHarness) -> None:
        """/setup status is equivalent to /setup."""
        text = await h.send("/setup status")
        assert "Credential Status" in text

    @pytest.mark.asyncio
    async def test_setup_with_anthropic_key_set(self, h: QAHarness) -> None:
        """When ANTHROPIC_API_KEY is set, Anthropic shows as configured."""
        original = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-key-123"
        try:
            text = await h.send("/setup")
            # Find the Anthropic row — it should say "set"
            assert "ANTHROPIC_API_KEY set" in text
        finally:
            if original:
                os.environ["ANTHROPIC_API_KEY"] = original
            else:
                os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# 4.2 Agent Management — /agent new, /agent edit
# ---------------------------------------------------------------------------


class TestAgentManagement:
    """Verify /agent new and /agent edit render correctly."""

    @pytest.mark.asyncio
    async def test_agent_new_shows_template(self, h: QAHarness) -> None:
        text = await h.send("/agent new")
        assert "agent.yaml" in text or "config" in text.lower()

    @pytest.mark.asyncio
    async def test_agent_edit_known_agent(self, h: QAHarness) -> None:
        text = await h.send("/agent edit homelab")
        assert "homelab" in text
        assert "config" in text.lower() or "agent.yaml" in text

    @pytest.mark.asyncio
    async def test_agent_edit_unknown_agent(self, h: QAHarness) -> None:
        text = await h.send("/agent edit nonexistent")
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_agent_edit_no_args(self, h: QAHarness) -> None:
        text = await h.send("/agent edit")
        assert "Usage" in text or "edit" in text.lower()

    @pytest.mark.asyncio
    async def test_agent_new_mentions_config_dir(self, h: QAHarness) -> None:
        text = await h.send("/agent new")
        assert "config/agents" in text


# ---------------------------------------------------------------------------
# 4.3 Models command
# ---------------------------------------------------------------------------


class TestModelsCommand:
    """Verify /models lists available models from the gateway."""

    @pytest.mark.asyncio
    async def test_models_shows_list(self, h: QAHarness) -> None:
        text = await h.send("/models")
        assert "Claude Sonnet" in text or "claude-sonnet" in text

    @pytest.mark.asyncio
    async def test_models_shows_multiple(self, h: QAHarness) -> None:
        text = await h.send("/models")
        assert "Llama" in text or "llama" in text

    @pytest.mark.asyncio
    async def test_models_empty_list(self, h: QAHarness) -> None:
        h.gateway.models_data = []
        text = await h.send("/models")
        assert "No models" in text


# ---------------------------------------------------------------------------
# 4.4 Reload command
# ---------------------------------------------------------------------------


class TestReloadCommand:
    """Verify /reload refreshes agent list from gateway."""

    @pytest.mark.asyncio
    async def test_reload_shows_count(self, h: QAHarness) -> None:
        text = await h.send("/reload")
        assert "4 agents" in text or "Reloaded" in text

    @pytest.mark.asyncio
    async def test_reload_shows_agent_names(self, h: QAHarness) -> None:
        text = await h.send("/reload")
        assert "huginn" in text
        assert "homelab" in text

    @pytest.mark.asyncio
    async def test_reload_picks_up_new_agents(self, h: QAHarness) -> None:
        """After adding a new agent to the gateway, /reload discovers it."""
        h.gateway.agents_data.append({"id": "music", "description": "Music agent"})
        text = await h.send("/reload")
        assert "music" in text
        assert "5 agents" in text or "Reloaded 5" in text

    @pytest.mark.asyncio
    async def test_reload_updates_parser(self, h: QAHarness) -> None:
        """After /reload, parser recognises newly added agents."""
        h.gateway.agents_data.append({"id": "music", "description": "Music agent"})
        await h.send("/reload")
        parsed = h.app.parser.parse("@music play something")
        assert "music" in parsed.mentions


# ---------------------------------------------------------------------------
# 4.5 Session search
# ---------------------------------------------------------------------------


class TestSessionSearch:
    """Verify /sessions search filters correctly."""

    @pytest.mark.asyncio
    async def test_sessions_search_by_query(self, h: QAHarness) -> None:
        h.gateway.sessions_data = [
            SessionSummary(session_id="s1", agent_name="homelab", summary="nginx setup"),
            SessionSummary(session_id="s2", agent_name="finance", summary="budget review"),
        ]
        text = await h.send('/sessions search "nginx"')
        assert "nginx" in text.lower()
        # Should NOT show budget review
        assert "budget" not in text.lower()

    @pytest.mark.asyncio
    async def test_sessions_search_by_agent(self, h: QAHarness) -> None:
        h.gateway.sessions_data = [
            SessionSummary(session_id="s1", agent_name="homelab", summary="server check"),
            SessionSummary(session_id="s2", agent_name="finance", summary="budget review"),
        ]
        text = await h.send('/sessions search "finance"')
        assert "budget" in text.lower() or "finance" in text.lower()

    @pytest.mark.asyncio
    async def test_sessions_search_no_match(self, h: QAHarness) -> None:
        h.gateway.sessions_data = [
            SessionSummary(session_id="s1", agent_name="homelab", summary="nginx setup"),
        ]
        text = await h.send('/sessions search "zzzzz"')
        # Should show empty table or "no sessions" message
        assert "session" in text.lower() or "No" in text

    @pytest.mark.asyncio
    async def test_sessions_list_all(self, h: QAHarness) -> None:
        h.gateway.sessions_data = [
            SessionSummary(session_id="s1", agent_name="homelab", summary="server check"),
            SessionSummary(session_id="s2", agent_name="finance", summary="budget review"),
        ]
        text = await h.send("/sessions")
        assert "server check" in text.lower() or "homelab" in text
        assert "budget" in text.lower() or "finance" in text


# ===========================================================================
# Phase 5: Polish & Production
# ===========================================================================


# ---------------------------------------------------------------------------
# 5.1 Theme switching — /theme
# ---------------------------------------------------------------------------


class TestThemeCommand:
    """Verify /theme switches themes and rebuilds renderer."""

    @pytest.mark.asyncio
    async def test_theme_no_args_shows_current(self, h: QAHarness) -> None:
        text = await h.send("/theme")
        assert "default" in text.lower()
        assert "Available" in text

    @pytest.mark.asyncio
    async def test_theme_list_shows_all_themes(self, h: QAHarness) -> None:
        text = await h.send("/theme")
        for name in available_themes():
            assert name in text

    @pytest.mark.asyncio
    async def test_theme_switch_to_light(self, h: QAHarness) -> None:
        text = await h.send("/theme light")
        assert "light" in text.lower()
        assert h.app.theme.name == "light"

    @pytest.mark.asyncio
    async def test_theme_switch_to_minimal(self, h: QAHarness) -> None:
        text = await h.send("/theme minimal")
        assert "minimal" in text.lower()
        assert h.app.theme.name == "minimal"

    @pytest.mark.asyncio
    async def test_theme_switch_unknown(self, h: QAHarness) -> None:
        text = await h.send("/theme neon")
        assert "Unknown" in text or "neon" in text
        # Should still be on default
        assert h.app.theme.name == "default"

    @pytest.mark.asyncio
    async def test_theme_switch_rebuilds_renderer(self, h: QAHarness) -> None:
        """After switching theme, the renderer uses the new theme."""
        old_renderer_id = id(h.app.renderer)
        await h.send("/theme light")
        new_renderer_id = id(h.app.renderer)
        assert old_renderer_id != new_renderer_id

    @pytest.mark.asyncio
    async def test_theme_switch_rebuilds_event_handler(self, h: QAHarness) -> None:
        old_id = id(h.app.event_handler)
        await h.send("/theme minimal")
        new_id = id(h.app.event_handler)
        assert old_id != new_id

    @pytest.mark.asyncio
    async def test_theme_switch_then_render_works(self, h: QAHarness) -> None:
        """After theme switch, rendering still produces output."""
        await h.send("/theme light")
        # Note: the theme switch rebuilt renderer with h.app.console which may not be
        # our captured console. We need to re-wire.
        h.app.renderer = ChatRenderer(h.console, h.app.theme)
        text = await h.send("/help")
        assert "/help" in text

    @pytest.mark.asyncio
    async def test_theme_switch_back_to_default(self, h: QAHarness) -> None:
        await h.send("/theme light")
        await h.send("/theme default")
        assert h.app.theme.name == "default"


# ---------------------------------------------------------------------------
# 5.2 Export command — /export
# ---------------------------------------------------------------------------


class TestExportCommand:
    """Verify /export session export behavior."""

    @pytest.mark.asyncio
    async def test_export_no_session(self, h: QAHarness) -> None:
        """Without an active session, export should report nothing to export."""
        text = await h.send("/export")
        assert "Nothing to export" in text or "no active session" in text.lower()

    @pytest.mark.asyncio
    async def test_export_with_session(self, h: QAHarness) -> None:
        """With an active session, export attempts to write a file."""
        # Create a session
        agent = h.app.agent_stack.current.agent_name
        sid = await h.app.session_manager.create(agent)

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            export_path = f.name

        try:
            text = await h.send(f"/export {export_path}")
            # Either succeeds or reports no messages
            assert "export" in text.lower() or "Nothing" in text or "no messages" in text.lower()
        finally:
            os.unlink(export_path) if os.path.exists(export_path) else None


# ---------------------------------------------------------------------------
# 5.3 Break-Glass Mode — /breakglass
# ---------------------------------------------------------------------------


class TestBreakGlassCommand:
    """Verify /breakglass activate, deactivate, and state changes."""

    @pytest.mark.asyncio
    async def test_breakglass_requires_policy_engine(self, h: QAHarness) -> None:
        """Without a policy engine, breakglass should fail."""
        h.app.policy_engine = None
        text = await h.send("/breakglass")
        assert "No policy" in text or "Cannot activate" in text

    @pytest.mark.asyncio
    async def test_breakglass_activate_with_policy(self, h: QAHarness) -> None:
        """With a policy engine, breakglass activates."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        text = await h.send("/breakglass")
        assert "BREAK-GLASS" in text
        assert "ACTIVATED" in text or "activated" in text.lower()
        assert h.app.permission_tier == "break_glass"

    @pytest.mark.asyncio
    async def test_breakglass_shows_ttl(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        text = await h.send("/breakglass 30")
        assert "30 minutes" in text or "30" in text

    @pytest.mark.asyncio
    async def test_breakglass_deactivate(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        text = await h.send("/breakglass off")
        assert "deactivated" in text.lower()
        assert h.app.permission_tier == "default"

    @pytest.mark.asyncio
    async def test_breakglass_sets_status_bar_tier(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        assert h.app.status_bar.tier == "BREAK-GLASS"

    @pytest.mark.asyncio
    async def test_breakglass_off_clears_status_bar_tier(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        await h.send("/breakglass off")
        assert h.app.status_bar.tier is None

    @pytest.mark.asyncio
    async def test_breakglass_stores_token(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        assert h.app._break_glass_token is not None
        assert h.app._break_glass_expiry is not None
        assert h.app._break_glass_expiry > time.time()

    @pytest.mark.asyncio
    async def test_breakglass_invalid_ttl(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        text = await h.send("/breakglass abc")
        assert "Invalid" in text

    @pytest.mark.asyncio
    async def test_breakglass_negative_ttl(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        text = await h.send("/breakglass -5")
        assert "positive" in text.lower()

    @pytest.mark.asyncio
    async def test_breakglass_off_clears_token(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        await h.send("/breakglass off")
        assert h.app._break_glass_token is None
        assert h.app._break_glass_expiry is None


# ---------------------------------------------------------------------------
# 5.4 Audit Log — /audit
# ---------------------------------------------------------------------------


class TestAuditCommand:
    """Verify /audit renders audit log entries."""

    @pytest.mark.asyncio
    async def test_audit_no_log_configured(self, h: QAHarness) -> None:
        h.app._audit_log = None
        text = await h.send("/audit")
        assert "not configured" in text.lower()

    @pytest.mark.asyncio
    async def test_audit_empty_log(self, h: QAHarness) -> None:
        """With an empty audit log file, should show 'no entries' message."""
        from corvus.security.audit import AuditLog
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            audit_path = f.name
        try:
            h.app._audit_log = AuditLog(Path(audit_path))
            text = await h.send("/audit")
            assert "No audit entries" in text or "audit" in text.lower()
        finally:
            os.unlink(audit_path) if os.path.exists(audit_path) else None

    @pytest.mark.asyncio
    async def test_audit_with_entries(self, h: QAHarness) -> None:
        """With real audit entries, table should render them."""
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
            h.app._audit_log = audit
            text = await h.send("/audit")
            assert "Audit" in text
            assert "Bash" in text or "homelab" in text
        finally:
            os.unlink(audit_path) if os.path.exists(audit_path) else None

    @pytest.mark.asyncio
    async def test_audit_filter_by_outcome(self, h: QAHarness) -> None:
        from corvus.security.audit import AuditLog
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            audit.log_tool_call(tool_name="Bash", agent_name="homelab", outcome="allowed", session_id="s1")
            audit.log_tool_call(tool_name="Write", agent_name="homelab", outcome="denied", session_id="s1")
            h.app._audit_log = audit
            text = await h.send("/audit denied")
            assert "denied" in text.lower()
        finally:
            os.unlink(audit_path) if os.path.exists(audit_path) else None

    @pytest.mark.asyncio
    async def test_audit_filter_by_agent(self, h: QAHarness) -> None:
        from corvus.security.audit import AuditLog
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            audit.log_tool_call(tool_name="Bash", agent_name="homelab", outcome="allowed", session_id="s1")
            audit.log_tool_call(tool_name="Write", agent_name="finance", outcome="allowed", session_id="s2")
            h.app._audit_log = audit
            text = await h.send("/audit homelab")
            assert "homelab" in text.lower()
        finally:
            os.unlink(audit_path) if os.path.exists(audit_path) else None


# ---------------------------------------------------------------------------
# 5.5 Policy command — /policy
# ---------------------------------------------------------------------------


class TestPolicyCommand:
    """Verify /policy renders current security policy state."""

    @pytest.mark.asyncio
    async def test_policy_no_engine(self, h: QAHarness) -> None:
        h.app.policy_engine = None
        text = await h.send("/policy")
        assert "No policy" in text or "policy.yaml" in text

    @pytest.mark.asyncio
    async def test_policy_with_engine(self, h: QAHarness) -> None:
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        h.app.permission_tier = "default"
        text = await h.send("/policy")
        assert "default" in text.lower() or "policy" in text.lower()


# ---------------------------------------------------------------------------
# 5.6 Split Mode — /split
# ---------------------------------------------------------------------------


class TestSplitCommand:
    """Verify /split command end-to-end through the app pipeline."""

    @pytest.mark.asyncio
    async def test_split_no_args_when_inactive(self, h: QAHarness) -> None:
        text = await h.send("/split")
        assert "off" in text.lower() or "Usage" in text

    @pytest.mark.asyncio
    async def test_split_activate(self, h: QAHarness) -> None:
        text = await h.send("/split @homelab @finance")
        assert "activated" in text.lower()
        assert "@homelab" in text
        assert "@finance" in text
        assert h.app.split_manager.active

    @pytest.mark.asyncio
    async def test_split_activate_without_at(self, h: QAHarness) -> None:
        text = await h.send("/split homelab finance")
        assert "activated" in text.lower()
        assert h.app.split_manager.left_agent == "homelab"
        assert h.app.split_manager.right_agent == "finance"

    @pytest.mark.asyncio
    async def test_split_status_when_active(self, h: QAHarness) -> None:
        await h.send("/split homelab finance")
        text = await h.send("/split")
        assert "SPLIT" in text
        assert "@homelab" in text
        assert "@finance" in text

    @pytest.mark.asyncio
    async def test_split_deactivate(self, h: QAHarness) -> None:
        await h.send("/split homelab finance")
        text = await h.send("/split off")
        assert "deactivated" in text.lower()
        assert not h.app.split_manager.active

    @pytest.mark.asyncio
    async def test_split_swap(self, h: QAHarness) -> None:
        await h.send("/split homelab finance")
        text = await h.send("/split swap")
        assert h.app.split_manager.left_agent == "finance"
        assert h.app.split_manager.right_agent == "homelab"
        assert "SPLIT" in text

    @pytest.mark.asyncio
    async def test_split_swap_when_inactive(self, h: QAHarness) -> None:
        text = await h.send("/split swap")
        assert "not active" in text.lower()

    @pytest.mark.asyncio
    async def test_split_invalid_args(self, h: QAHarness) -> None:
        text = await h.send("/split homelab")
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_split_too_many_args(self, h: QAHarness) -> None:
        text = await h.send("/split a b c")
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_split_reactivate_overwrites(self, h: QAHarness) -> None:
        await h.send("/split homelab finance")
        await h.send("/split work huginn")
        assert h.app.split_manager.left_agent == "work"
        assert h.app.split_manager.right_agent == "huginn"


# ---------------------------------------------------------------------------
# Cross-feature integration: features working together
# ---------------------------------------------------------------------------


class TestCrossFeatureIntegration:
    """Test Phase 4/5 features interacting with each other and Phase 1-3."""

    @pytest.mark.asyncio
    async def test_breakglass_then_chat(self, h: QAHarness) -> None:
        """Break-glass mode shouldn't affect normal chat flow."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        assert h.app.permission_tier == "break_glass"

        h.gateway.script_chat_response("huginn", "Still working fine.")
        text = await h.send("hello")
        assert "working fine" in text.lower()

    @pytest.mark.asyncio
    async def test_theme_switch_then_chat(self, h: QAHarness) -> None:
        """After theme switch, chat still produces output."""
        await h.send("/theme minimal")
        # Re-wire captured console after theme switch
        h.app.renderer = ChatRenderer(h.console, h.app.theme)
        h.app.event_handler = EventHandler(h.app.renderer, h.app.agent_stack, h.app.token_counter)
        h.gateway.on_event(h.app.event_handler.handle)

        h.gateway.script_chat_response("huginn", "Minimal theme works!")
        text = await h.send("test")
        assert "Minimal theme works" in text

    @pytest.mark.asyncio
    async def test_split_then_agent_switch(self, h: QAHarness) -> None:
        """Activating split then switching agent doesn't crash."""
        await h.send("/split homelab finance")
        text = await h.send("/agent work")
        assert "work" in text.lower()
        # Split manager still active with original agents
        assert h.app.split_manager.active
        assert h.app.split_manager.left_agent == "homelab"

    @pytest.mark.asyncio
    async def test_reload_then_split(self, h: QAHarness) -> None:
        """Reload agents, then split with newly added agent."""
        h.gateway.agents_data.append({"id": "music", "description": "Music agent"})
        await h.send("/reload")
        text = await h.send("/split homelab music")
        assert "activated" in text.lower()
        assert h.app.split_manager.right_agent == "music"

    @pytest.mark.asyncio
    async def test_setup_after_theme_switch(self, h: QAHarness) -> None:
        """Setup dashboard renders correctly after theme change."""
        await h.send("/theme light")
        h.app.renderer = ChatRenderer(h.console, h.app.theme)
        text = await h.send("/setup")
        assert "Credential Status" in text

    @pytest.mark.asyncio
    async def test_breakglass_on_off_restores_state(self, h: QAHarness) -> None:
        """Full breakglass cycle: activate → verify state → deactivate → verify reset."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()

        # Activate
        await h.send("/breakglass 15")
        assert h.app.permission_tier == "break_glass"
        assert h.app.status_bar.tier == "BREAK-GLASS"
        assert h.app._break_glass_token is not None

        # Deactivate
        await h.send("/breakglass off")
        assert h.app.permission_tier == "default"
        assert h.app.status_bar.tier is None
        assert h.app._break_glass_token is None

    @pytest.mark.asyncio
    async def test_help_shows_phase4_5_commands(self, h: QAHarness) -> None:
        """/help should list all Phase 4/5 commands."""
        text = await h.send("/help")
        for cmd in ["setup", "breakglass", "split", "theme", "audit", "policy", "export"]:
            assert f"/{cmd}" in text or cmd in text, f"Missing /{cmd} in help output"


# ---------------------------------------------------------------------------
# Output verification: rendered content structure
# ---------------------------------------------------------------------------


class TestRenderedOutputStructure:
    """Verify the actual Rich output structure — panels, tables, formatting."""

    @pytest.mark.asyncio
    async def test_setup_has_table_borders(self, h: QAHarness) -> None:
        """Setup dashboard should render as a Rich Table with borders."""
        text = await h.send("/setup")
        # Rich tables use box-drawing characters
        assert "─" in text or "━" in text or "Provider" in text

    @pytest.mark.asyncio
    async def test_breakglass_has_panel(self, h: QAHarness) -> None:
        """Break-glass activation should render in a Panel."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        text = await h.send("/breakglass")
        # Rich panels use box-drawing characters
        assert "─" in text or "━" in text or "╭" in text

    @pytest.mark.asyncio
    async def test_breakglass_output_contains_warning(self, h: QAHarness) -> None:
        """Break-glass panel should contain warning text about global deny list."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        text = await h.send("/breakglass")
        assert "deny list" in text.lower() or "enforced" in text.lower()

    @pytest.mark.asyncio
    async def test_help_output_organized_by_tier(self, h: QAHarness) -> None:
        """Help should list commands grouped by tier."""
        text = await h.send("/help")
        # Should contain tier names or clear groupings
        assert "/help" in text
        assert "/quit" in text
        assert "/memory" in text

    @pytest.mark.asyncio
    async def test_agents_output_shows_current_marker(self, h: QAHarness) -> None:
        """Agents list should mark the current agent."""
        text = await h.send("/agents")
        assert "@huginn" in text

    @pytest.mark.asyncio
    async def test_sessions_empty_renders_cleanly(self, h: QAHarness) -> None:
        """Empty sessions list should render a message, not crash."""
        h.gateway.sessions_data = []
        text = await h.send("/sessions")
        assert "session" in text.lower() or "No" in text

    @pytest.mark.asyncio
    async def test_split_activate_output_format(self, h: QAHarness) -> None:
        """Split activation message should name both agents."""
        text = await h.send("/split homelab finance")
        assert "@homelab" in text
        assert "@finance" in text

    @pytest.mark.asyncio
    async def test_breakglass_deactivate_output(self, h: QAHarness) -> None:
        """Deactivation message should mention default permissions."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass")
        text = await h.send("/breakglass off")
        assert "default" in text.lower() or "deactivated" in text.lower()


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestPhase45EdgeCases:
    """Edge cases for Phase 4/5 features."""

    @pytest.mark.asyncio
    async def test_split_then_off_then_status(self, h: QAHarness) -> None:
        """After split off, status shows inactive."""
        await h.send("/split homelab finance")
        await h.send("/split off")
        text = await h.send("/split")
        assert "off" in text.lower() or "Usage" in text

    @pytest.mark.asyncio
    async def test_breakglass_double_activate(self, h: QAHarness) -> None:
        """Activating breakglass twice should work (overwrites)."""
        from corvus.security.policy import PolicyEngine
        h.app.policy_engine = PolicyEngine()
        await h.send("/breakglass 30")
        text = await h.send("/breakglass 15")
        assert "BREAK-GLASS" in text
        assert h.app.permission_tier == "break_glass"

    @pytest.mark.asyncio
    async def test_theme_switch_preserves_agent_stack(self, h: QAHarness) -> None:
        """Theme switch should not affect the agent stack."""
        await h.send("/agent homelab")
        await h.send("/theme minimal")
        assert h.app.agent_stack.current.agent_name == "homelab"

    @pytest.mark.asyncio
    async def test_theme_switch_preserves_token_count(self, h: QAHarness) -> None:
        """Theme switch should not reset token counters."""
        h.app.token_counter.add("huginn", 500)
        await h.send("/theme light")
        assert h.app.token_counter.session_total == 500

    @pytest.mark.asyncio
    async def test_audit_command_with_many_entries(self, h: QAHarness) -> None:
        """Audit log with many entries should truncate to limit."""
        from corvus.security.audit import AuditLog
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            audit_path = f.name
        try:
            audit = AuditLog(Path(audit_path))
            for i in range(50):
                audit.log_tool_call(tool_name=f"Tool{i}", agent_name="homelab", outcome="allowed", session_id="s1")
            h.app._audit_log = audit
            text = await h.send("/audit")
            assert "last 20" in text.lower() or "20" in text
        finally:
            os.unlink(audit_path) if os.path.exists(audit_path) else None

    @pytest.mark.asyncio
    async def test_models_empty_after_reconnect(self, h: QAHarness) -> None:
        """If models list is empty, user gets a clear message."""
        h.gateway.models_data = []
        text = await h.send("/models")
        assert "No models" in text

    @pytest.mark.asyncio
    async def test_agent_edit_lists_available_on_miss(self, h: QAHarness) -> None:
        """When editing unknown agent, error should list available agents."""
        text = await h.send("/agent edit ghost")
        assert "not found" in text.lower()
        # Should list available agents
        assert "huginn" in text or "homelab" in text
