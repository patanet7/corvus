"""SetupScreen — credential dashboard and provider status overview.

Renders a table of configured providers with their connection status,
replacing the inline /setup command output with a richer display.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from corvus.tui.core.credentials import _get_credential_status
from corvus.tui.screens.base import Screen
from corvus.tui.theme import TuiTheme


class SetupScreen(Screen):
    """Interactive setup/credential dashboard screen."""

    def __init__(self, console: Console, theme: TuiTheme) -> None:
        super().__init__(console, theme)
        self._providers: list[dict] = []

    @property
    def title(self) -> str:
        return "Setup & Credentials"

    def load_providers(self) -> None:
        """Scan environment variables and populate provider status."""
        self._providers = _get_credential_status()

    def render(self) -> None:
        """Render the setup dashboard as a table inside a panel."""
        if not self._providers:
            self.load_providers()

        table = Table(
            title=self.title,
            show_header=True,
            header_style=f"bold {self._theme.tool_border}",
            expand=True,
        )
        table.add_column("Provider", style="bold")
        table.add_column("Status", width=12, justify="center")
        table.add_column("Detail")

        for p in self._providers:
            status = Text("OK", style="bold green") if p["configured"] else Text("Missing", style="bold red")
            table.add_row(p["name"], status, p["detail"])

        configured = sum(1 for p in self._providers if p["configured"])
        total = len(self._providers)
        summary = f"{configured}/{total} providers configured"

        panel = Panel(
            table,
            subtitle=summary,
            border_style=self._theme.tool_border,
        )
        self._console.print(panel)
