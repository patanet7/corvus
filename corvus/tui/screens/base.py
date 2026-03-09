"""Base screen class for Corvus TUI interactive screens.

Screens are full-display overlays that temporarily replace the chat view.
Each screen renders Rich content to the console and handles user interaction
within its own display loop.
"""

from abc import ABC, abstractmethod

from rich.console import Console

from corvus.tui.theme import TuiTheme


class Screen(ABC):
    """Abstract base for interactive TUI screens.

    Screens are activated by commands (e.g. /setup, /agents) and render
    a full-console display.  They exit back to the chat loop when the
    user presses 'q', Escape, or a screen-specific exit action.
    """

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        self._console = console
        self._theme = theme

    @property
    @abstractmethod
    def title(self) -> str:
        """Human-readable screen title (e.g. 'Setup', 'Agents')."""

    @abstractmethod
    def render(self) -> None:
        """Render the screen content to the console."""

    def header(self) -> str:
        """Return the screen header text (default: title)."""
        return self.title
