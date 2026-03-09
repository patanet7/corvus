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
    """Theme configuration for the Corvus TUI.

    Every visual style used by the renderer is defined here so that
    swapping themes only requires changing this class.
    """

    # UI chrome
    border: str = "dim"
    muted: str = "dim"
    system: str = "dim italic"
    status_bar: str = "reverse"

    # Welcome banner
    welcome_title: str = "bold bright_white"
    welcome_subtitle: str = "italic"
    welcome_border: str = "bright_magenta"

    # User messages
    user_label: str = "bold bright_white"
    user_text: str = "bright_white"
    user_arrow: str = "dim"

    # Agent messages / streaming
    stream_hint: str = "dim italic"

    # Tool panels
    tool_border: str = "cyan"
    tool_result_border: str = "green"
    tool_syntax_theme: str = "monokai"

    # Confirm prompt
    confirm_border: str = "yellow"
    confirm_title: str = "bold yellow"
    confirm_yes: str = "bold green"
    confirm_no: str = "bold red"
    confirm_always: str = "bold cyan"

    # Errors / warnings / success
    error: str = "bold red"
    error_border: str = "red"
    warning: str = "bold yellow"
    success: str = "bold green"

    # Tables
    table_border: str = "dim"
    table_command: str = "bold cyan"
    table_tier: str = "dim italic"
    active_marker: str = "bold green"

    # Memory table
    memory_id: str = "dim"
    memory_content: str = "bright_white"
    memory_domain: str = "bright_cyan"
    memory_score: str = "bright_yellow"

    # Tools table
    tool_name: str = "bold cyan"
    tool_type: str = "dim italic"
    tool_description: str = "bright_white"

    # File view / diff
    file_view_border: str = "bright_blue"
    file_view_syntax_theme: str = "monokai"
    diff_border: str = "bright_yellow"
    diff_syntax_theme: str = "monokai"

    # Theme name
    name: str = "default"

    def __init__(self, name: str = "default") -> None:
        self._fallback_assignments: dict[str, str] = {}
        self._fallback_index: int = 0
        self.name = name
        if name != "default":
            self._apply_theme(name)

    def _apply_theme(self, name: str) -> None:
        """Apply a named theme preset."""
        preset = THEME_PRESETS.get(name)
        if not preset:
            return
        for attr, value in preset.items():
            if hasattr(self, attr):
                setattr(self, attr, value)

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


# ---------------------------------------------------------------------------
# Theme presets
# ---------------------------------------------------------------------------

THEME_PRESETS: dict[str, dict[str, str]] = {
    "default": {},  # All defaults (dark theme)
    "light": {
        "border": "grey50",
        "muted": "grey50",
        "system": "grey50 italic",
        "status_bar": "on white",
        "user_label": "bold black",
        "user_text": "black",
        "error": "bold red",
        "success": "bold green",
        "warning": "bold dark_orange",
        "tool_syntax_theme": "github-dark",
        "file_view_syntax_theme": "github-dark",
        "diff_syntax_theme": "github-dark",
    },
    "minimal": {
        "border": "dim",
        "muted": "dim",
        "system": "dim",
        "status_bar": "dim reverse",
        "welcome_border": "dim",
        "confirm_border": "dim",
        "tool_border": "dim",
        "tool_result_border": "dim",
        "error_border": "dim",
        "table_border": "dim",
    },
}


def available_themes() -> list[str]:
    """Return list of available theme names."""
    return list(THEME_PRESETS.keys())
