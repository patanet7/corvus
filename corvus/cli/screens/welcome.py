"""Welcome screen — first screen in the setup wizard."""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Header, Static


class WelcomeScreen(Screen):
    """Welcome screen with project intro and Next button."""

    BINDINGS = [("escape", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("CLAW SETUP", id="title")
        yield Static(
            "\nWelcome to Claw — your personal agent.\n\n"
            "This wizard will configure your\n"
            "credentials and get you running.\n",
            id="description",
        )
        yield Button("Next →", id="next-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-btn":
            self.app.push_screen("backends")
