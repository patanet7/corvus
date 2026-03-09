"""Token counter for per-agent and session-total token tracking."""


class TokenCounter:
    """Track token usage per-agent and session total."""

    def __init__(self) -> None:
        self._agent_counts: dict[str, int] = {}
        self._session_total: int = 0

    def add(self, agent: str, tokens: int) -> None:
        """Record token usage for an agent."""
        self._agent_counts[agent] = self._agent_counts.get(agent, 0) + tokens
        self._session_total += tokens

    @property
    def session_total(self) -> int:
        """Return the session-wide total token count."""
        return self._session_total

    def agent_total(self, agent: str) -> int:
        """Return total tokens for a specific agent, 0 if unknown."""
        return self._agent_counts.get(agent, 0)

    @property
    def all_agents(self) -> dict[str, int]:
        """Return a copy of per-agent token counts."""
        return dict(self._agent_counts)

    def reset(self) -> None:
        """Clear all token counts."""
        self._agent_counts.clear()
        self._session_total = 0

    def format_display(self) -> str:
        """Format for status bar, e.g. '45.1k tok'."""
        if self._session_total >= 1000:
            return f"{self._session_total / 1000:.1f}k tok"
        return f"{self._session_total} tok"
