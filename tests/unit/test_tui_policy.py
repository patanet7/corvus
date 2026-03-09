"""Behavioral tests for TUI policy display (Task 5.2).

Tests exercise real PolicyEngine instances and real Rich Console rendering.
No mocks, no monkeypatch, no @patch.
"""

import asyncio
import io

from prompt_toolkit.formatted_text import HTML
from rich.console import Console

from corvus.security.policy import PolicyEngine, TierConfig
from corvus.tui.app import TuiApp
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.input.parser import InputParser, ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.theme import TuiTheme


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


def _make_policy_engine() -> PolicyEngine:
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
                max_ttl=14400,
            ),
        },
    )


def _make_minimal_policy_engine() -> PolicyEngine:
    """Create a minimal PolicyEngine with no deny patterns and no tiers."""
    return PolicyEngine(global_deny=[], tiers={})


# ---------------------------------------------------------------------------
# render_policy — current tier display
# ---------------------------------------------------------------------------


class TestRenderPolicyCurrentTier:
    """render_policy shows the current tier name prominently."""

    def test_shows_current_tier_name_default(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        assert "default" in output.lower()

    def test_shows_current_tier_name_strict(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="strict")
        output = _output(buf)
        assert "strict" in output.lower()

    def test_shows_current_tier_name_break_glass(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="break_glass")
        output = _output(buf)
        assert "break_glass" in output.lower()


# ---------------------------------------------------------------------------
# render_policy — global deny patterns
# ---------------------------------------------------------------------------


class TestRenderPolicyGlobalDeny:
    """render_policy shows global deny patterns."""

    def test_shows_deny_patterns(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        assert "*.env*" in output
        assert "*.ssh/*" in output
        assert "*credentials*" in output
        assert "*.pem" in output

    def test_empty_deny_shows_none_label(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_minimal_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        # Should indicate no deny patterns
        assert "none" in output.lower() or "no " in output.lower()


# ---------------------------------------------------------------------------
# render_policy — tier configuration details
# ---------------------------------------------------------------------------


class TestRenderPolicyTierConfig:
    """render_policy shows tier configuration details."""

    def test_shows_confirm_default(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        assert "deny" in output.lower()

    def test_shows_mode(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        assert "allowlist_with_baseline" in output

    def test_break_glass_shows_auth_required(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="break_glass")
        output = _output(buf)
        assert "auth" in output.lower() or "true" in output.lower()

    def test_break_glass_shows_token_ttl(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="break_glass")
        output = _output(buf)
        assert "3600" in output

    def test_unknown_tier_handled_gracefully(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_policy_engine()
        renderer.render_policy(engine, current_tier="nonexistent")
        output = _output(buf)
        # Should still render without crashing, showing the tier name
        assert "nonexistent" in output.lower()


# ---------------------------------------------------------------------------
# render_policy — minimal/empty policy
# ---------------------------------------------------------------------------


class TestRenderPolicyMinimal:
    """render_policy handles empty or minimal policy gracefully."""

    def test_empty_engine_renders_without_error(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_minimal_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        assert len(output) > 0  # Something was rendered

    def test_no_tiers_shows_no_config(self) -> None:
        renderer, buf = _make_renderer()
        engine = _make_minimal_policy_engine()
        renderer.render_policy(engine, current_tier="default")
        output = _output(buf)
        # Should indicate no tier config available
        assert "no tier config" in output.lower() or "not configured" in output.lower()


# ---------------------------------------------------------------------------
# StatusBar — tier indicator
# ---------------------------------------------------------------------------


class TestStatusBarTier:
    """StatusBar shows tier indicator when set."""

    def _make_status_bar(self) -> tuple[StatusBar, AgentStack, TokenCounter]:
        stack = AgentStack()
        counter = TokenCounter()
        theme = TuiTheme()
        bar = StatusBar(stack, counter, theme)
        return bar, stack, counter

    def test_no_tier_by_default(self) -> None:
        bar, _stack, _counter = self._make_status_bar()
        result = bar()
        # No tier indicator when not set
        assert isinstance(result, HTML)

    def test_tier_property_default_is_none(self) -> None:
        bar, _stack, _counter = self._make_status_bar()
        assert bar.tier is None

    def test_tier_setter_updates_display(self) -> None:
        bar, stack, _counter = self._make_status_bar()
        stack.push("work", session_id="s1")
        bar.tier = "default"
        result = bar()
        assert "default" in result.value.lower()

    def test_tier_strict_shown(self) -> None:
        bar, stack, _counter = self._make_status_bar()
        stack.push("work", session_id="s1")
        bar.tier = "strict"
        result = bar()
        assert "strict" in result.value.lower()

    def test_tier_break_glass_shown(self) -> None:
        bar, stack, _counter = self._make_status_bar()
        stack.push("work", session_id="s1")
        bar.tier = "break_glass"
        result = bar()
        assert "break_glass" in result.value.lower()

    def test_tier_none_not_shown(self) -> None:
        bar, stack, _counter = self._make_status_bar()
        stack.push("work", session_id="s1")
        bar.tier = None
        result = bar()
        text = result.value
        # "tier" label should not appear when tier is None
        assert "strict" not in text.lower()
        assert "break_glass" not in text.lower()


# ---------------------------------------------------------------------------
# TuiApp — policy attributes
# ---------------------------------------------------------------------------


class TestTuiAppPolicyAttributes:
    """TuiApp has permission_tier and policy_engine attributes."""

    def test_permission_tier_defaults_to_default(self) -> None:
        app = TuiApp()
        assert app.permission_tier == "default"

    def test_policy_engine_defaults_to_none(self) -> None:
        app = TuiApp()
        assert app.policy_engine is None

    def test_policy_engine_can_be_set(self) -> None:
        app = TuiApp()
        engine = _make_policy_engine()
        app.policy_engine = engine
        assert app.policy_engine is engine

    def test_permission_tier_can_be_set(self) -> None:
        app = TuiApp()
        app.permission_tier = "strict"
        assert app.permission_tier == "strict"


# ---------------------------------------------------------------------------
# TuiApp — /policy command handler
# ---------------------------------------------------------------------------


class TestTuiAppPolicyCommand:
    """TuiApp._handle_policy_command renders policy info via ChatRenderer."""

    def test_policy_command_no_engine_shows_message(self) -> None:
        app = TuiApp()
        app.policy_engine = None
        buf = io.StringIO()
        app.console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(app.console, app.theme)

        asyncio.run(
            app._handle_policy_command()
        )
        buf.seek(0)
        output = buf.read()
        assert "no policy loaded" in output.lower()

    def test_policy_command_with_engine_shows_tier(self) -> None:
        app = TuiApp()
        app.policy_engine = _make_policy_engine()
        app.permission_tier = "default"
        buf = io.StringIO()
        app.console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(app.console, app.theme)

        asyncio.run(
            app._handle_policy_command()
        )
        buf.seek(0)
        output = buf.read()
        assert "default" in output.lower()

    def test_policy_command_with_engine_shows_deny(self) -> None:
        app = TuiApp()
        app.policy_engine = _make_policy_engine()
        app.permission_tier = "strict"
        buf = io.StringIO()
        app.console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(app.console, app.theme)

        asyncio.run(
            app._handle_policy_command()
        )
        buf.seek(0)
        output = buf.read()
        assert "*.env*" in output


# ---------------------------------------------------------------------------
# TuiApp — /policy wired in _handle_service_command
# ---------------------------------------------------------------------------


class TestTuiAppPolicyServiceWiring:
    """The /policy command is dispatched through _handle_service_command."""

    def test_policy_dispatched_from_service_handler(self) -> None:
        app = TuiApp()
        app.policy_engine = _make_policy_engine()
        app.permission_tier = "default"
        buf = io.StringIO()
        app.console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(app.console, app.theme)

        parsed = ParsedInput(
            raw="/policy",
            kind="command",
            text="/policy",
            command="policy",
            command_args="",
            mentions=[],
            tool_name=None,
            tool_args=None,
        )
        result = asyncio.run(
            app._handle_service_command(parsed)
        )
        assert result is True
        buf.seek(0)
        output = buf.read()
        assert "default" in output.lower()
