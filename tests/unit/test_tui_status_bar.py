"""Behavioral tests for the TUI StatusBar component.

All tests use real AgentStack, TokenCounter, and TuiTheme objects.
No mocks, no monkeypatch, no @patch.
"""

from prompt_toolkit.formatted_text import HTML

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.output.status_bar import StatusBar
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.theme import TuiTheme


def _make_status_bar() -> tuple[StatusBar, AgentStack, TokenCounter]:
    """Create a StatusBar with real dependencies."""
    stack = AgentStack()
    counter = TokenCounter()
    theme = TuiTheme()
    bar = StatusBar(stack, counter, theme)
    return bar, stack, counter


class TestStatusBarAgent:
    """Agent name display in the status bar."""

    def test_empty_stack_shows_corvus(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert isinstance(result, HTML)
        # Extract the text value from the HTML
        text = result.value
        assert "corvus" in text
        assert "@" not in text.split("|")[0]  # "corvus" not prefixed with @

    def test_agent_pushed_shows_at_agent(self) -> None:
        bar, stack, _counter = _make_status_bar()
        stack.push("work", session_id="s1")
        result = bar()
        assert "@work" in result.value

    def test_agent_switch_updates_display(self) -> None:
        bar, stack, _counter = _make_status_bar()
        stack.push("work", session_id="s1")
        assert "@work" in bar().value

        stack.switch("finance", session_id="s2")
        result = bar()
        assert "@finance" in result.value
        assert "@work" not in result.value


class TestStatusBarModel:
    """Model name display in the status bar."""

    def test_default_model_shown(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert "default" in result.value

    def test_custom_model_shown(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        bar.model = "claude-opus-4-20250514"
        result = bar()
        assert "claude-opus-4-20250514" in result.value

    def test_model_property_getter(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        assert bar.model == "default"
        bar.model = "gpt-4"
        assert bar.model == "gpt-4"


class TestStatusBarWorkers:
    """Worker count display in the status bar."""

    def test_zero_workers_not_shown(self) -> None:
        bar, stack, _counter = _make_status_bar()
        stack.push("work", session_id="s1")
        result = bar()
        assert "workers" not in result.value

    def test_one_worker_shown(self) -> None:
        bar, stack, _counter = _make_status_bar()
        stack.push("work", session_id="s1")
        stack.spawn("codex", session_id="s2")
        result = bar()
        assert "workers: 1" in result.value

    def test_multiple_workers_shown(self) -> None:
        bar, stack, _counter = _make_status_bar()
        stack.push("work", session_id="s1")
        stack.spawn("codex", session_id="s2")
        stack.spawn("researcher", session_id="s3")
        stack.spawn("writer", session_id="s4")
        result = bar()
        assert "workers: 3" in result.value

    def test_workers_not_shown_on_empty_stack(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert "workers" not in result.value


class TestStatusBarTokens:
    """Token count display in the status bar."""

    def test_zero_tokens(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert "0 tok" in result.value

    def test_tokens_after_add(self) -> None:
        bar, _stack, counter = _make_status_bar()
        counter.add("work", 500)
        result = bar()
        assert "500 tok" in result.value

    def test_tokens_large_count_formatted(self) -> None:
        bar, _stack, counter = _make_status_bar()
        counter.add("work", 45100)
        result = bar()
        assert "45.1k tok" in result.value

    def test_tokens_update_dynamically(self) -> None:
        bar, _stack, counter = _make_status_bar()
        assert "0 tok" in bar().value

        counter.add("work", 1000)
        assert "1.0k tok" in bar().value

        counter.add("finance", 2500)
        assert "3.5k tok" in bar().value


class TestStatusBarCallable:
    """StatusBar is callable and returns HTML."""

    def test_is_callable(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        assert callable(bar)

    def test_returns_html(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert isinstance(result, HTML)

    def test_html_has_bold_tags(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert "<b>" in result.value
        assert "</b>" in result.value


class TestStatusBarIntegration:
    """Full integration: multiple state changes reflected in output."""

    def test_full_state_reflected(self) -> None:
        bar, stack, counter = _make_status_bar()
        bar.model = "claude-sonnet"

        stack.push("homelab", session_id="s1")
        stack.spawn("docker-agent", session_id="s2")
        counter.add("homelab", 12300)

        result = bar()
        text = result.value
        assert "@homelab" in text
        assert "claude-sonnet" in text
        assert "workers: 1" in text
        assert "12.3k tok" in text

    def test_pipe_separator(self) -> None:
        bar, _stack, _counter = _make_status_bar()
        result = bar()
        assert " | " in result.value


class TestStatusBarCostDisplay:
    """Cost display in the status bar — Task #19."""

    def test_no_cost_shows_tokens_only(self) -> None:
        bar, _stack, counter = _make_status_bar()
        counter.add("work", 5000)
        result = bar()
        assert "5.0k tok" in result.value
        assert "$" not in result.value

    def test_cost_shown_after_add_cost(self) -> None:
        bar, _stack, counter = _make_status_bar()
        counter.add("work", 5000)
        counter.add_cost("work", 0.22)
        result = bar()
        assert "5.0k tok" in result.value
        assert "$0.22" in result.value

    def test_cost_updates_dynamically(self) -> None:
        bar, _stack, counter = _make_status_bar()
        counter.add("work", 1000)
        assert "$" not in bar().value

        counter.add_cost("work", 0.05)
        assert "$0.05" in bar().value

        counter.add_cost("finance", 0.10)
        assert "$0.15" in bar().value

    def test_cost_with_full_state(self) -> None:
        bar, stack, counter = _make_status_bar()
        bar.model = "claude-sonnet"
        stack.push("homelab", session_id="s1")
        counter.add("homelab", 12300)
        counter.add_cost("homelab", 1.05)

        result = bar()
        text = result.value
        assert "@homelab" in text
        assert "claude-sonnet" in text
        assert "12.3k tok" in text
        assert "$1.05" in text
