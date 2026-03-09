"""SetupScreen — credential dashboard and provider status overview.

Renders a table of configured providers with their connection status,
replacing the inline /setup command output with a richer display.
"""

import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
        self._providers = _scan_providers()

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


def _scan_providers() -> list[dict]:
    """Check environment variables for each provider and return status list."""
    providers: list[dict] = []

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    providers.append({
        "name": "Anthropic",
        "configured": bool(anthropic_key),
        "detail": "ANTHROPIC_API_KEY set" if anthropic_key else "ANTHROPIC_API_KEY missing",
    })

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    providers.append({
        "name": "OpenAI",
        "configured": bool(openai_key),
        "detail": "OPENAI_API_KEY set" if openai_key else "OPENAI_API_KEY missing",
    })

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    providers.append({
        "name": "Ollama",
        "configured": True,
        "detail": ollama_host,
    })

    gmail_creds = os.environ.get("GMAIL_CREDENTIALS", "")
    google_client = os.environ.get("GOOGLE_CLIENT_ID", "")
    gmail_configured = bool(gmail_creds or google_client)
    if gmail_creds:
        gmail_detail = "GMAIL_CREDENTIALS set"
    elif google_client:
        gmail_detail = "GOOGLE_CLIENT_ID set"
    else:
        gmail_detail = "GMAIL_CREDENTIALS or GOOGLE_CLIENT_ID missing"
    providers.append({
        "name": "Gmail",
        "configured": gmail_configured,
        "detail": gmail_detail,
    })

    ha_token = os.environ.get("HA_TOKEN", "")
    ha_url = os.environ.get("HA_URL", "")
    ha_configured = bool(ha_token or ha_url)
    if ha_token:
        ha_detail = "HA_TOKEN set"
    elif ha_url:
        ha_detail = f"HA_URL: {ha_url}"
    else:
        ha_detail = "HA_TOKEN or HA_URL missing"
    providers.append({
        "name": "Home Assistant",
        "configured": ha_configured,
        "detail": ha_detail,
    })

    paperless_token = os.environ.get("PAPERLESS_TOKEN", "")
    paperless_url = os.environ.get("PAPERLESS_URL", "")
    paperless_configured = bool(paperless_token or paperless_url)
    if paperless_token:
        paperless_detail = "PAPERLESS_TOKEN set"
    elif paperless_url:
        paperless_detail = f"PAPERLESS_URL: {paperless_url}"
    else:
        paperless_detail = "PAPERLESS_TOKEN or PAPERLESS_URL missing"
    providers.append({
        "name": "Paperless",
        "configured": paperless_configured,
        "detail": paperless_detail,
    })

    firefly_token = os.environ.get("FIREFLY_TOKEN", "")
    firefly_url = os.environ.get("FIREFLY_URL", "")
    firefly_configured = bool(firefly_token or firefly_url)
    if firefly_token:
        firefly_detail = "FIREFLY_TOKEN set"
    elif firefly_url:
        firefly_detail = f"FIREFLY_URL: {firefly_url}"
    else:
        firefly_detail = "FIREFLY_TOKEN or FIREFLY_URL missing"
    providers.append({
        "name": "Firefly",
        "configured": firefly_configured,
        "detail": firefly_detail,
    })

    return providers
