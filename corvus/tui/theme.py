"""Corvus TUI theme system — agent colors and UI chrome constants."""

AGENT_COLORS: dict[str, str] = {
    "huginn": "bright_magenta",
    "work": "bright_blue",
    "homelab": "bright_green",
    "finance": "bright_yellow",
    "personal": "bright_cyan",
    "music": "bright_red",
    "docs": "bright_white",
    "inbox": "orange1",
    "email": "orange1",
    "home": "cyan",
    "general": "white",
}

_FALLBACK_COLORS: list[str] = [
    "deep_sky_blue1",
    "spring_green1",
    "gold1",
    "orchid1",
    "turquoise2",
    "salmon1",
    "medium_purple1",
    "chartreuse1",
]


class TuiTheme:
    """Theme configuration for the Corvus TUI."""

    # UI chrome colors
    border: str = "dim"
    muted: str = "dim"
    error: str = "bold red"
    warning: str = "bold yellow"
    success: str = "bold green"
    system: str = "dim italic"
    user_label: str = "bold bright_white"
    status_bar: str = "reverse"

    def __init__(self) -> None:
        self._fallback_assignments: dict[str, str] = {}
        self._fallback_index: int = 0

    def agent_color(self, agent_name: str) -> str:
        """Return the Rich color string for an agent.

        Known agents get their configured color. Unknown agents are assigned
        a stable fallback color from the rotation pool.
        """
        if agent_name in AGENT_COLORS:
            return AGENT_COLORS[agent_name]

        if agent_name not in self._fallback_assignments:
            color = _FALLBACK_COLORS[self._fallback_index % len(_FALLBACK_COLORS)]
            self._fallback_assignments[agent_name] = color
            self._fallback_index += 1

        return self._fallback_assignments[agent_name]
