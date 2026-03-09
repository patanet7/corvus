"""Behavioral tests for TokenCounter — per-agent and session tracking."""

from corvus.tui.output.token_counter import TokenCounter


class TestTokenCounterAccumulation:
    """Adding tokens accumulates correctly per agent and session."""

    def test_single_agent_single_add(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 100)
        assert counter.agent_total("huginn") == 100
        assert counter.session_total == 100

    def test_single_agent_multiple_adds(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 100)
        counter.add("huginn", 250)
        counter.add("huginn", 50)
        assert counter.agent_total("huginn") == 400
        assert counter.session_total == 400

    def test_multiple_agents_tracked_independently(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 100)
        counter.add("work", 200)
        counter.add("finance", 300)
        assert counter.agent_total("huginn") == 100
        assert counter.agent_total("work") == 200
        assert counter.agent_total("finance") == 300

    def test_session_total_across_agents(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 100)
        counter.add("work", 200)
        counter.add("huginn", 50)
        counter.add("finance", 300)
        assert counter.session_total == 650

    def test_all_agents_returns_copy(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 100)
        counter.add("work", 200)
        agents = counter.all_agents
        assert agents == {"huginn": 100, "work": 200}
        # Mutating the returned dict must not affect internal state.
        agents["huginn"] = 9999
        assert counter.agent_total("huginn") == 100


class TestTokenCounterDefaults:
    """Unknown agents and fresh counters return safe defaults."""

    def test_unknown_agent_returns_zero(self) -> None:
        counter = TokenCounter()
        assert counter.agent_total("nonexistent") == 0

    def test_fresh_counter_session_total_is_zero(self) -> None:
        counter = TokenCounter()
        assert counter.session_total == 0

    def test_fresh_counter_all_agents_is_empty(self) -> None:
        counter = TokenCounter()
        assert counter.all_agents == {}


class TestTokenCounterReset:
    """reset() clears all state."""

    def test_reset_clears_session_total(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 500)
        counter.add("work", 300)
        counter.reset()
        assert counter.session_total == 0

    def test_reset_clears_agent_counts(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 500)
        counter.add("work", 300)
        counter.reset()
        assert counter.agent_total("huginn") == 0
        assert counter.agent_total("work") == 0
        assert counter.all_agents == {}

    def test_add_after_reset_starts_fresh(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 500)
        counter.reset()
        counter.add("huginn", 100)
        assert counter.agent_total("huginn") == 100
        assert counter.session_total == 100


class TestTokenCounterFormatDisplay:
    """format_display() renders human-readable token counts."""

    def test_zero_tokens(self) -> None:
        counter = TokenCounter()
        assert counter.format_display() == "0 tok"

    def test_below_thousand(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 42)
        assert counter.format_display() == "42 tok"

    def test_below_thousand_boundary(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 999)
        assert counter.format_display() == "999 tok"

    def test_exactly_one_thousand(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 1000)
        assert counter.format_display() == "1.0k tok"

    def test_fractional_thousands(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 1500)
        assert counter.format_display() == "1.5k tok"

    def test_large_count(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 45_100)
        assert counter.format_display() == "45.1k tok"

    def test_very_large_count(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 123_456)
        assert counter.format_display() == "123.5k tok"

    def test_format_display_reflects_multiple_agents(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 500)
        counter.add("work", 700)
        assert counter.format_display() == "1.2k tok"


# ===========================================================================
# Cost tracking — Task #19
# ===========================================================================


class TestCostAccumulation:
    """add_cost accumulates USD cost per-agent and session-wide."""

    def test_single_agent_single_cost(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.05)
        assert counter.agent_cost("huginn") == 0.05
        assert counter.session_cost == 0.05

    def test_single_agent_multiple_costs(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.05)
        counter.add_cost("huginn", 0.10)
        assert abs(counter.agent_cost("huginn") - 0.15) < 1e-9
        assert abs(counter.session_cost - 0.15) < 1e-9

    def test_multiple_agents_tracked_independently(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.05)
        counter.add_cost("work", 0.12)
        counter.add_cost("finance", 0.03)
        assert counter.agent_cost("huginn") == 0.05
        assert counter.agent_cost("work") == 0.12
        assert counter.agent_cost("finance") == 0.03

    def test_session_cost_across_agents(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.05)
        counter.add_cost("work", 0.10)
        counter.add_cost("huginn", 0.02)
        assert abs(counter.session_cost - 0.17) < 1e-9

    def test_unknown_agent_cost_returns_zero(self) -> None:
        counter = TokenCounter()
        assert counter.agent_cost("nonexistent") == 0.0

    def test_fresh_counter_session_cost_is_zero(self) -> None:
        counter = TokenCounter()
        assert counter.session_cost == 0.0


class TestCostReset:
    """reset() clears cost state along with token state."""

    def test_reset_clears_session_cost(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.50)
        counter.add_cost("work", 0.30)
        counter.reset()
        assert counter.session_cost == 0.0

    def test_reset_clears_agent_costs(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.50)
        counter.reset()
        assert counter.agent_cost("huginn") == 0.0

    def test_add_cost_after_reset_starts_fresh(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.50)
        counter.reset()
        counter.add_cost("huginn", 0.10)
        assert counter.agent_cost("huginn") == 0.10
        assert counter.session_cost == 0.10


class TestFormatCost:
    """format_cost() renders USD with two decimal places."""

    def test_zero_cost(self) -> None:
        counter = TokenCounter()
        assert counter.format_cost() == "$0.00"

    def test_small_cost(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.0312)
        assert counter.format_cost() == "$0.03"

    def test_dollar_plus_cost(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 1.0567)
        assert counter.format_cost() == "$1.06"

    def test_accumulated_cost(self) -> None:
        counter = TokenCounter()
        counter.add_cost("huginn", 0.10)
        counter.add_cost("work", 0.12)
        assert counter.format_cost() == "$0.22"


class TestFormatDisplayWithCost:
    """format_display() includes cost when cost > 0."""

    def test_no_cost_shows_tokens_only(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 5000)
        assert counter.format_display() == "5.0k tok"

    def test_with_cost_shows_tokens_and_cost(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 5000)
        counter.add_cost("huginn", 0.22)
        assert counter.format_display() == "5.0k tok \u00b7 $0.22"

    def test_small_tokens_with_cost(self) -> None:
        counter = TokenCounter()
        counter.add("huginn", 42)
        counter.add_cost("huginn", 0.01)
        assert counter.format_display() == "42 tok \u00b7 $0.01"

    def test_zero_tokens_zero_cost(self) -> None:
        counter = TokenCounter()
        assert counter.format_display() == "0 tok"
