"""Setup complete summary screen."""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Header, Static

BACKEND_LABELS = {
    "claude": "Claude (Anthropic)",
    "openai": "OpenAI",
    "ollama": "Ollama (local)",
    "kimi": "Kimi / Moonshot",
    "openai-compat": "OpenAI-compatible",
}

SERVICE_LABELS = {
    "ha": "Home Assistant",
    "paperless": "Paperless",
    "firefly": "Firefly III",
    "obsidian": "Obsidian",
}


class CompleteScreen(Screen):
    """Summary of what was configured, with save and exit."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("SETUP COMPLETE", id="title")

        lines: list[str] = ["\n  LLM Backends"]

        backends = getattr(self.app, "_backends_data", {})
        for backend_id, label in BACKEND_LABELS.items():
            if backend_id in backends:
                lines.append(f"    {label:<24s} configured")
            else:
                lines.append(f"    {label:<24s} skipped")

        lines.append("\n  Services")

        services = getattr(self.app, "_services_data", {})
        for svc_id, label in SERVICE_LABELS.items():
            if svc_id in services:
                lines.append(f"    {label:<24s} configured")
            else:
                lines.append(f"    {label:<24s} skipped")

        lines.append("")

        if getattr(self.app, "_passphrase_set", False):
            lines.append("  Break-glass passphrase   set")
        else:
            lines.append("  Break-glass passphrase   skipped")

        yield Static("\n".join(lines) + "\n", id="summary")
        yield Static("\nCredentials will be encrypted to:\n~/.corvus/credentials.json\n")
        yield Static("\nStart Corvus:  mise run serve\n")
        yield Button("Save & Exit", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self.app._save_credentials()  # type: ignore[attr-defined]
            self.app.exit()
