"""Service credentials configuration screen.

Shows input fields for each integration (HA, Paperless, Firefly, Obsidian).
Each service has URL + Token fields.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Static

SERVICES = [
    ("ha", "Home Assistant", "url", "token"),
    ("paperless", "Paperless", "url", "token"),
    ("firefly", "Firefly III", "url", "token"),
    ("obsidian", "Obsidian", "url", "token"),
]


class ServicesScreen(Screen):
    """Service credential input form."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("SERVICE CREDENTIALS", id="title")
        yield Static("\nConfigure integrations (skip any):\n")

        for svc_id, label, key1, key2 in SERVICES:
            with Vertical(id=f"svc-{svc_id}"):
                yield Static(f"  {label}", classes="svc-label")
                with Horizontal():
                    yield Input(
                        placeholder=f"{label} URL",
                        id=f"{svc_id}-{key1}",
                    )
                    yield Input(
                        placeholder=f"{label} Token",
                        id=f"{svc_id}-{key2}",
                        password=True,
                    )

        yield Button("\u2190 Back", id="back-btn")
        yield Button("Next \u2192", id="next-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            services_data: dict[str, dict[str, str]] = {}
            for svc_id, _label, key1, key2 in SERVICES:
                url_val = self.query_one(f"#{svc_id}-{key1}", Input).value
                token_val = self.query_one(f"#{svc_id}-{key2}", Input).value
                if url_val or token_val:
                    services_data[svc_id] = {}
                    if url_val:
                        services_data[svc_id][key1] = url_val
                    if token_val:
                        services_data[svc_id][key2] = token_val
            self.app._services_data = services_data  # type: ignore[attr-defined]
            self.app.push_screen("passphrase")
