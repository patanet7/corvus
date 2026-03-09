"""Token counter for per-agent and session-total token and cost tracking."""


class TokenCounter:
    """Track token usage and USD cost per-agent and session total."""

    def __init__(self) -> None:
        self._agent_counts: dict[str, int] = {}
        self._session_total: int = 0
        self._agent_costs: dict[str, float] = {}
        self._session_cost_total: float = 0.0

    def add(self, agent: str, tokens: int) -> None:
        """Record token usage for an agent."""
        self._agent_counts[agent] = self._agent_counts.get(agent, 0) + tokens
        self._session_total += tokens

    def add_cost(self, agent: str, cost: float) -> None:
        """Record USD cost for an agent run."""
        self._agent_costs[agent] = self._agent_costs.get(agent, 0.0) + cost
        self._session_cost_total += cost

    @property
    def session_total(self) -> int:
        """Return the session-wide total token count."""
        return self._session_total

    @property
    def session_cost(self) -> float:
        """Return the session-wide total USD cost."""
        return self._session_cost_total

    def agent_total(self, agent: str) -> int:
        """Return total tokens for a specific agent, 0 if unknown."""
        return self._agent_counts.get(agent, 0)

    def agent_cost(self, agent: str) -> float:
        """Return total USD cost for a specific agent, 0.0 if unknown."""
        return self._agent_costs.get(agent, 0.0)

    @property
    def all_agents(self) -> dict[str, int]:
        """Return a copy of per-agent token counts."""
        return dict(self._agent_counts)

    def reset(self) -> None:
        """Clear all token and cost counts."""
        self._agent_counts.clear()
        self._session_total = 0
        self._agent_costs.clear()
        self._session_cost_total = 0.0

    def format_cost(self) -> str:
        """Format session cost for display, e.g. '$0.22' or '$1.05'."""
        return f"${self._session_cost_total:.2f}"

    def format_display(self) -> str:
        """Format for status bar, e.g. '45.1k tok' or '5.0k tok · $0.22'."""
        if self._session_total >= 1000:
            tok = f"{self._session_total / 1000:.1f}k tok"
        else:
            tok = f"{self._session_total} tok"
        if self._session_cost_total > 0:
            return f"{tok} \u00b7 {self.format_cost()}"
        return tok
