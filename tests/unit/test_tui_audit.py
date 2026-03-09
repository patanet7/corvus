"""Behavioral tests for /audit command and audit log rendering.

Uses real AuditLog writing to real temp JSONL files — no mocks.
"""

import io
import tempfile
from pathlib import Path

from rich.console import Console

from corvus.security.audit import AuditLog
from corvus.tui.commands.builtins import ServiceCommandHandler
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.in_process import InProcessGateway
from corvus.tui.theme import TuiTheme


def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    """Build a ChatRenderer backed by a string buffer for assertions."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    return renderer, buf


def _output(buf: io.StringIO) -> str:
    """Return everything written so far and reset."""
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


def _seed_audit_log(log_path: Path) -> AuditLog:
    """Create an AuditLog with sample entries covering multiple agents/outcomes."""
    audit = AuditLog(log_path)
    audit.log_tool_call(
        agent_name="homelab",
        session_id="sess-001",
        tool_name="restart_service",
        outcome="allowed",
        duration_ms=120.5,
    )
    audit.log_tool_call(
        agent_name="finance",
        session_id="sess-002",
        tool_name="transfer_funds",
        outcome="denied",
        reason="Policy violation",
        duration_ms=5.0,
    )
    audit.log_tool_call(
        agent_name="homelab",
        session_id="sess-001",
        tool_name="read_logs",
        outcome="allowed",
        duration_ms=45.2,
    )
    audit.log_tool_call(
        agent_name="work",
        session_id="sess-003",
        tool_name="send_email",
        outcome="failed",
        reason="Timeout",
        duration_ms=3000.0,
    )
    audit.log_tool_call(
        agent_name="finance",
        session_id="sess-002",
        tool_name="check_balance",
        outcome="allowed",
        duration_ms=30.1,
    )
    return audit


class _FakePolicyRef:
    """Minimal stand-in for SystemCommandHandler providing policy_engine and permission_tier."""

    policy_engine = None
    permission_tier = "default"


def _make_svc_handler(
    renderer: ChatRenderer, audit_log: AuditLog | None,
) -> ServiceCommandHandler:
    """Build a ServiceCommandHandler with minimal real dependencies for audit tests."""
    from corvus.tui.core.session import TuiSessionManager

    agent_stack = AgentStack()
    gateway = InProcessGateway()
    token_counter = TokenCounter()
    session_manager = TuiSessionManager(gateway, agent_stack)
    return ServiceCommandHandler(
        renderer=renderer,
        agent_stack=agent_stack,
        gateway=gateway,
        token_counter=token_counter,
        session_manager=session_manager,
        audit_log=audit_log,
        policy_engine_ref=_FakePolicyRef(),
    )


# ---------------------------------------------------------------------------
# render_audit_entries tests
# ---------------------------------------------------------------------------


class TestRenderAuditEntries:
    """Tests for ChatRenderer.render_audit_entries()."""

    def test_render_audit_entries_shows_table_with_columns(self) -> None:
        """Rendered table includes timestamp, agent, tool, outcome, and duration columns."""
        renderer, buf = _make_renderer()
        entries = [
            {
                "timestamp": "2026-03-09T10:00:00+00:00",
                "agent_name": "homelab",
                "tool_name": "restart_service",
                "outcome": "allowed",
                "duration_ms": 120.5,
                "session_id": "sess-001",
                "reason": None,
                "params_summary": None,
            }
        ]
        renderer.render_audit_entries(entries)
        output = _output(buf)
        assert "homelab" in output
        assert "restart_service" in output
        assert "allowed" in output
        assert "120.5" in output

    def test_render_audit_entries_empty_shows_no_entries_message(self) -> None:
        """Empty entry list renders 'No audit entries found.' message."""
        renderer, buf = _make_renderer()
        renderer.render_audit_entries([])
        output = _output(buf)
        assert "No audit entries found" in output

    def test_render_audit_entries_multiple_rows(self) -> None:
        """Multiple entries each produce a row in the output."""
        renderer, buf = _make_renderer()
        entries = [
            {
                "timestamp": "2026-03-09T10:00:00+00:00",
                "agent_name": "homelab",
                "tool_name": "restart_service",
                "outcome": "allowed",
                "duration_ms": 120.5,
                "session_id": "sess-001",
                "reason": None,
                "params_summary": None,
            },
            {
                "timestamp": "2026-03-09T10:01:00+00:00",
                "agent_name": "finance",
                "tool_name": "transfer_funds",
                "outcome": "denied",
                "duration_ms": 5.0,
                "session_id": "sess-002",
                "reason": "Policy violation",
                "params_summary": None,
            },
        ]
        renderer.render_audit_entries(entries)
        output = _output(buf)
        assert "homelab" in output
        assert "finance" in output
        assert "restart_service" in output
        assert "transfer_funds" in output

    def test_render_audit_entries_custom_title(self) -> None:
        """Custom title appears in the rendered output."""
        renderer, buf = _make_renderer()
        entries = [
            {
                "timestamp": "2026-03-09T10:00:00+00:00",
                "agent_name": "homelab",
                "tool_name": "read_logs",
                "outcome": "allowed",
                "duration_ms": 45.2,
                "session_id": "sess-001",
                "reason": None,
                "params_summary": None,
            }
        ]
        renderer.render_audit_entries(entries, title="Homelab Audit")
        output = _output(buf)
        assert "Homelab Audit" in output


# ---------------------------------------------------------------------------
# _handle_audit tests — uses real AuditLog on real temp file
# ---------------------------------------------------------------------------


class TestHandleAuditCommand:
    """Tests for ServiceCommandHandler._handle_audit() with real JSONL files."""

    def test_audit_no_args_shows_recent_entries(self) -> None:
        """No args shows all recent entries from the audit log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            audit = _seed_audit_log(log_path)
            renderer, buf = _make_renderer()

            handler = _make_svc_handler(renderer, audit)
            handler._handle_audit(None)
            output = _output(buf)
            # Should show entries from all agents
            assert "homelab" in output
            assert "finance" in output
            assert "work" in output

    def test_audit_filter_by_agent(self) -> None:
        """Passing an agent name filters entries to that agent only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            audit = _seed_audit_log(log_path)
            renderer, buf = _make_renderer()

            handler = _make_svc_handler(renderer, audit)
            handler._handle_audit("homelab")
            output = _output(buf)
            assert "homelab" in output
            assert "restart_service" in output
            assert "read_logs" in output
            # finance/work entries should not be present
            assert "transfer_funds" not in output
            assert "send_email" not in output

    def test_audit_filter_by_denied_outcome(self) -> None:
        """Passing 'denied' filters to denied-outcome entries only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            audit = _seed_audit_log(log_path)
            renderer, buf = _make_renderer()

            handler = _make_svc_handler(renderer, audit)
            handler._handle_audit("denied")
            output = _output(buf)
            assert "transfer_funds" in output
            assert "denied" in output.lower()
            # allowed/failed entries should not appear
            assert "restart_service" not in output
            assert "send_email" not in output

    def test_audit_filter_by_failed_outcome(self) -> None:
        """Passing 'failed' filters to failed-outcome entries only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            audit = _seed_audit_log(log_path)
            renderer, buf = _make_renderer()

            handler = _make_svc_handler(renderer, audit)
            handler._handle_audit("failed")
            output = _output(buf)
            assert "send_email" in output
            assert "restart_service" not in output
            assert "transfer_funds" not in output

    def test_audit_empty_log_file(self) -> None:
        """Empty audit log shows 'No audit entries found'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            audit = AuditLog(log_path)
            renderer, buf = _make_renderer()

            handler = _make_svc_handler(renderer, audit)
            handler._handle_audit(None)
            output = _output(buf)
            assert "No audit entries found" in output

    def test_audit_no_audit_log_configured(self) -> None:
        """When audit_log is None, shows a helpful message."""
        renderer, buf = _make_renderer()

        handler = _make_svc_handler(renderer, None)
        handler._handle_audit(None)
        output = _output(buf)
        assert "Audit log not configured" in output

    def test_audit_limits_to_20_entries(self) -> None:
        """Without a filter, output is capped to the last 20 entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            audit = AuditLog(log_path)
            # Write 30 entries
            for i in range(30):
                audit.log_tool_call(
                    agent_name="homelab",
                    session_id="sess-bulk",
                    tool_name=f"tool_{i:03d}",
                    outcome="allowed",
                    duration_ms=float(i),
                )
            renderer, buf = _make_renderer()

            handler = _make_svc_handler(renderer, audit)
            handler._handle_audit(None)
            output = _output(buf)
            # Last 20 entries: tool_010 through tool_029
            assert "tool_029" in output
            assert "tool_010" in output
            # First 10 entries should NOT appear
            assert "tool_009" not in output
            assert "tool_000" not in output
