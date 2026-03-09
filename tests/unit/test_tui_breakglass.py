"""Behavioral tests for TUI break-glass mode (Task 5.3).

Tests exercise real security module functions (create_break_glass_token,
PolicyEngine, TierConfig) and real Rich Console rendering.
No mocks, no monkeypatch, no @patch.
"""

import asyncio
import io
import time

from rich.console import Console

from corvus.security.policy import PolicyEngine, TierConfig
from corvus.security.tokens import create_break_glass_token, validate_break_glass_token
from corvus.tui.app import TuiApp
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.input.parser import ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.theme import TuiTheme

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TEST_SECRET = b"test-secret-key-for-break-glass-mode"  # 36 bytes, >= 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_policy_engine(max_ttl: int = 14400) -> PolicyEngine:
    """Create a realistic PolicyEngine with all three tiers."""
    return PolicyEngine(
        global_deny=["*.env*", "*.ssh/*", "*credentials*", "*.pem"],
        tiers={
            "strict": TierConfig(
                mode="allowlist",
                confirm_default="deny",
            ),
            "default": TierConfig(
                mode="allowlist_with_baseline",
                confirm_default="deny",
            ),
            "break_glass": TierConfig(
                mode="allow_all",
                confirm_default="allow",
                requires_auth=True,
                token_ttl=3600,
                max_ttl=max_ttl,
            ),
        },
    )


def _make_app_with_buffer(
    policy_engine: PolicyEngine | None = None,
) -> tuple[TuiApp, io.StringIO]:
    """Create a TuiApp with output captured to a string buffer."""
    app = TuiApp()
    buf = io.StringIO()
    app.console = Console(file=buf, force_terminal=True, width=120)
    app.renderer = ChatRenderer(app.console, app.theme)
    if policy_engine is not None:
        app.policy_engine = policy_engine
    return app, buf


def _parsed_breakglass(args: str | None = None) -> ParsedInput:
    """Create a ParsedInput simulating '/breakglass [args]'."""
    raw = "/breakglass" if args is None else f"/breakglass {args}"
    return ParsedInput(
        raw=raw,
        kind="command",
        text=raw,
        command="breakglass",
        command_args=args,
        mentions=[],
        tool_name=None,
        tool_args=None,
    )


# ---------------------------------------------------------------------------
# /breakglass activates break-glass mode
# ---------------------------------------------------------------------------


class TestBreakglassActivation:
    """'/breakglass' sets permission_tier to break_glass and creates a token."""

    def test_activates_break_glass_tier(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        assert app.permission_tier == "default"

        asyncio.run(app._handle_breakglass_command(None))

        assert app.permission_tier == "break_glass"

    def test_creates_token(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        assert app._break_glass_token is None

        asyncio.run(app._handle_breakglass_command(None))

        assert app._break_glass_token is not None
        assert isinstance(app._break_glass_token, str)
        assert "." in app._break_glass_token  # payload.signature format

    def test_token_is_valid(self) -> None:
        """The generated token can be validated with the same secret."""
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))

        token = app._break_glass_token
        assert token is not None
        # Token should be validatable (not expired, correct signature)
        payload = validate_break_glass_token(secret=app._break_glass_secret, token=token)
        assert payload["session_id"] is not None
        assert payload["exp"] > time.time()

    def test_sets_expiry_time(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))

        assert app._break_glass_expiry is not None
        assert app._break_glass_expiry > time.time()

    def test_default_ttl_is_60_minutes(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        before = time.time()
        asyncio.run(app._handle_breakglass_command(None))
        after = time.time()

        assert app._break_glass_expiry is not None
        # Default 60 minutes = 3600 seconds, within 2s tolerance
        expected_expiry_low = before + 3600 - 2
        expected_expiry_high = after + 3600 + 2
        assert expected_expiry_low <= app._break_glass_expiry <= expected_expiry_high

    def test_shows_activation_message(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))

        output = _output(buf)
        assert "break-glass" in output.lower() or "break_glass" in output.lower()
        assert "60" in output  # default 60 minutes


# ---------------------------------------------------------------------------
# /breakglass <ttl> — custom TTL
# ---------------------------------------------------------------------------


class TestBreakglassCustomTTL:
    """'/breakglass 30' uses a custom TTL of 30 minutes."""

    def test_custom_ttl_30_minutes(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        before = time.time()
        asyncio.run(app._handle_breakglass_command("30"))
        after = time.time()

        assert app._break_glass_expiry is not None
        expected_low = before + 1800 - 2  # 30 * 60
        expected_high = after + 1800 + 2
        assert expected_low <= app._break_glass_expiry <= expected_high

    def test_custom_ttl_shows_in_message(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command("30"))

        output = _output(buf)
        assert "30" in output

    def test_custom_ttl_5_minutes(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        before = time.time()
        asyncio.run(app._handle_breakglass_command("5"))
        after = time.time()

        assert app._break_glass_expiry is not None
        expected_low = before + 300 - 2
        expected_high = after + 300 + 2
        assert expected_low <= app._break_glass_expiry <= expected_high


# ---------------------------------------------------------------------------
# TTL clamping to policy max_ttl
# ---------------------------------------------------------------------------


class TestBreakglassTTLClamping:
    """TTL is clamped to policy engine's max_ttl."""

    def test_ttl_clamped_to_max(self) -> None:
        """Request 999 minutes but max_ttl is 14400s (240 minutes)."""
        app, buf = _make_app_with_buffer(_make_policy_engine(max_ttl=14400))
        before = time.time()
        asyncio.run(app._handle_breakglass_command("999"))
        after = time.time()

        assert app._break_glass_expiry is not None
        # Should be clamped to 14400 seconds (240 minutes)
        expected_low = before + 14400 - 2
        expected_high = after + 14400 + 2
        assert expected_low <= app._break_glass_expiry <= expected_high

    def test_ttl_clamped_to_small_max(self) -> None:
        """Request 60 minutes but max_ttl is 600s (10 minutes)."""
        app, buf = _make_app_with_buffer(_make_policy_engine(max_ttl=600))
        before = time.time()
        asyncio.run(app._handle_breakglass_command("60"))
        after = time.time()

        assert app._break_glass_expiry is not None
        expected_low = before + 600 - 2
        expected_high = after + 600 + 2
        assert expected_low <= app._break_glass_expiry <= expected_high

    def test_clamped_message_shows_actual_ttl(self) -> None:
        """When clamped, the message should show the clamped value."""
        app, buf = _make_app_with_buffer(_make_policy_engine(max_ttl=600))
        asyncio.run(app._handle_breakglass_command("60"))

        output = _output(buf)
        # Should show 10 (clamped minutes), not 60
        assert "10" in output


# ---------------------------------------------------------------------------
# /breakglass off — deactivation
# ---------------------------------------------------------------------------


class TestBreakglassDeactivation:
    """'/breakglass off' resets to default tier."""

    def test_off_resets_tier_to_default(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))
        assert app.permission_tier == "break_glass"

        asyncio.run(app._handle_breakglass_command("off"))
        assert app.permission_tier == "default"

    def test_off_clears_token(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))
        assert app._break_glass_token is not None

        asyncio.run(app._handle_breakglass_command("off"))
        assert app._break_glass_token is None

    def test_off_clears_expiry(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))
        assert app._break_glass_expiry is not None

        asyncio.run(app._handle_breakglass_command("off"))
        assert app._break_glass_expiry is None

    def test_off_shows_deactivation_message(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))
        _output(buf)  # clear activation message

        asyncio.run(app._handle_breakglass_command("off"))
        output = _output(buf)
        assert "deactivat" in output.lower() or "disabled" in output.lower()

    def test_off_updates_status_bar_tier(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))
        assert app.status_bar.tier == "BREAK-GLASS"

        asyncio.run(app._handle_breakglass_command("off"))
        assert app.status_bar.tier is None or app.status_bar.tier == "default"


# ---------------------------------------------------------------------------
# /breakglass without policy engine
# ---------------------------------------------------------------------------


class TestBreakglassNoPolicyEngine:
    """'/breakglass' without a policy engine shows an error."""

    def test_no_policy_engine_shows_error(self) -> None:
        app, buf = _make_app_with_buffer(policy_engine=None)
        asyncio.run(app._handle_breakglass_command(None))

        output = _output(buf)
        assert "error" in output.lower() or "no policy" in output.lower()

    def test_no_policy_engine_does_not_change_tier(self) -> None:
        app, buf = _make_app_with_buffer(policy_engine=None)
        asyncio.run(app._handle_breakglass_command(None))

        assert app.permission_tier == "default"

    def test_no_policy_engine_does_not_create_token(self) -> None:
        app, buf = _make_app_with_buffer(policy_engine=None)
        asyncio.run(app._handle_breakglass_command(None))

        assert app._break_glass_token is None


# ---------------------------------------------------------------------------
# Status bar shows break-glass indicator
# ---------------------------------------------------------------------------


class TestStatusBarBreakGlass:
    """Status bar shows BREAK-GLASS when mode is active."""

    def test_status_bar_shows_break_glass_label(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        asyncio.run(app._handle_breakglass_command(None))

        assert app.status_bar.tier is not None
        assert "break" in app.status_bar.tier.lower()

    def test_status_bar_renders_break_glass_in_toolbar(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        app.agent_stack.push("work", session_id="s1")
        asyncio.run(app._handle_breakglass_command(None))

        toolbar_html = app.status_bar()
        assert "BREAK-GLASS" in toolbar_html.value or "break" in toolbar_html.value.lower()


# ---------------------------------------------------------------------------
# Renderer — break-glass messages
# ---------------------------------------------------------------------------


class TestRendererBreakglassMessages:
    """ChatRenderer renders activation and deactivation messages."""

    def test_render_breakglass_activated(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_breakglass_activated(60)
        output = _output(buf)
        assert "break" in output.lower()
        assert "60" in output

    def test_render_breakglass_activated_custom_ttl(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_breakglass_activated(30)
        output = _output(buf)
        assert "30" in output

    def test_render_breakglass_deactivated(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_breakglass_deactivated()
        output = _output(buf)
        assert "deactivat" in output.lower() or "disabled" in output.lower()

    def test_render_breakglass_status_countdown(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_breakglass_status(1800)  # 30 minutes remaining
        output = _output(buf)
        assert "30" in output or "1800" in output


# ---------------------------------------------------------------------------
# /breakglass wired in _handle_system_command
# ---------------------------------------------------------------------------


class TestBreakglassSystemCommandWiring:
    """The /breakglass command is dispatched through _handle_system_command."""

    def test_breakglass_dispatched_from_system_handler(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        parsed = _parsed_breakglass()

        result = asyncio.run(app._handle_system_command(parsed))
        assert result is True
        assert app.permission_tier == "break_glass"

    def test_breakglass_off_dispatched_from_system_handler(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())

        # Activate first
        parsed_on = _parsed_breakglass()
        asyncio.run(app._handle_system_command(parsed_on))
        assert app.permission_tier == "break_glass"

        # Deactivate
        parsed_off = _parsed_breakglass("off")
        result = asyncio.run(app._handle_system_command(parsed_off))
        assert result is True
        assert app.permission_tier == "default"

    def test_breakglass_with_ttl_dispatched(self) -> None:
        app, buf = _make_app_with_buffer(_make_policy_engine())
        parsed = _parsed_breakglass("45")

        result = asyncio.run(app._handle_system_command(parsed))
        assert result is True
        assert app.permission_tier == "break_glass"


# ---------------------------------------------------------------------------
# Global deny list preserved in break-glass
# ---------------------------------------------------------------------------


class TestBreakglassGlobalDenyPreserved:
    """Break-glass mode preserves the global deny list concept."""

    def test_policy_engine_global_deny_unchanged_after_activation(self) -> None:
        engine = _make_policy_engine()
        app, buf = _make_app_with_buffer(engine)
        deny_before = list(engine.global_deny)

        asyncio.run(app._handle_breakglass_command(None))

        assert engine.global_deny == deny_before

    def test_compose_deny_list_still_includes_global_deny(self) -> None:
        engine = _make_policy_engine()
        app, buf = _make_app_with_buffer(engine)

        asyncio.run(app._handle_breakglass_command(None))

        deny = engine.compose_deny_list("break_glass", [])
        for pattern in ["*.env*", "*.ssh/*", "*credentials*", "*.pem"]:
            assert pattern in deny
