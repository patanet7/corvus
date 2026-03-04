"""Credential status dashboard screen."""

from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Header, Static

SERVICE_LABELS = {
    "anthropic": "Anthropic",
    "ha": "Home Assistant",
    "paperless": "Paperless",
    "firefly": "Firefly III",
    "obsidian": "Obsidian",
    "google": "Google OAuth",
    "yahoo": "Yahoo",
}


class StatusScreen(Screen):
    """Live credential status dashboard."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("CREDENTIAL STATUS", id="title")

        lines = self._build_status_lines()
        yield Static("\n" + "\n".join(lines) + "\n", id="status-body")
        yield Button("Quit", id="quit-btn")

    def _build_status_lines(self) -> list[str]:
        """Build status lines from credential store."""
        config_dir = Path.home() / ".corvus"
        creds_path = config_dir / "credentials.json"

        if not creds_path.exists():
            return [
                "  No credential store found.",
                f"  Expected: {creds_path}",
                "  Run: mise run setup",
            ]

        try:
            from corvus.credential_store import CredentialStore

            store = CredentialStore(path=creds_path)
            store.load()
            configured = store.services()
        except Exception as e:
            return [f"  Error loading store: {e}"]

        lines = [
            f"  {'Service':<18s} {'Status':<14s}",
            f"  {'─' * 18}  {'─' * 14}",
        ]
        for svc_id, label in SERVICE_LABELS.items():
            if svc_id in configured:
                lines.append(f"  {label:<18s} Configured")
            else:
                lines.append(f"  {label:<18s} Not configured")

        # Passphrase status
        from corvus.break_glass import BreakGlassManager

        mgr = BreakGlassManager(config_dir=config_dir)
        if mgr.has_passphrase():
            lines.append("\n  Break-glass: Passphrase set")
        else:
            lines.append("\n  Break-glass: No passphrase")

        lines.append(f"  Store: {creds_path}")
        return lines

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit-btn":
            self.app.exit()
