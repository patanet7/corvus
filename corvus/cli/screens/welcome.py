"""Welcome screen — first-run only, with age key backup.

Generates an age keypair if not present, displays the public key
for the user to back up, and navigates to the dashboard.
"""

import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Static


def get_or_create_age_keypair(key_file: Path) -> str:
    """Ensure age keypair exists and return the public key.

    Generates a new keypair with age-keygen if the file doesn't exist.
    Sets file permissions to 0o600.
    """
    if not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["age-keygen", "-o", str(key_file)],
            capture_output=True,
            check=True,
        )
        key_file.chmod(0o600)

    for line in key_file.read_text().splitlines():
        if line.startswith("# public key:"):
            return line.split(":", 1)[1].strip()

    raise RuntimeError(f"Could not find public key in {key_file}")


class WelcomeScreen(Screen):
    """First-run welcome screen with age key backup."""

    BINDINGS = [("escape", "app.quit", "Quit")]

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
    }
    #welcome-container {
        width: 60;
        height: auto;
        padding: 2 3;
    }
    #welcome-title {
        text-style: bold;
        color: $accent;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #welcome-description {
        text-align: center;
        margin-bottom: 1;
    }
    #key-display {
        border: round $primary;
        padding: 1;
        margin: 1 0;
        text-align: center;
    }
    #key-warning {
        color: $warning;
        margin: 1 0;
    }
    #get-started-btn {
        margin-top: 1;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="welcome-container"):
            yield Static("CORVUS SETUP", id="welcome-title")
            yield Static(
                "Welcome to Corvus — your personal agent.\n\n"
                "This wizard will set up your credentials.\n"
                "Everything is encrypted locally with SOPS+age.",
                id="welcome-description",
            )

            config_dir = Path.home() / ".corvus"
            key_file = config_dir / "age-key.txt"
            try:
                public_key = get_or_create_age_keypair(key_file)
            except Exception as exc:
                public_key = f"Error: {exc}"

            yield Static("Back up your recovery key:", id="key-label")
            yield Static(public_key, id="key-display")
            yield Static(
                "Store this somewhere safe. If you lose\n"
                "~/.corvus/age-key.txt, your credentials\n"
                "cannot be recovered.",
                id="key-warning",
            )
            yield Button("Get Started", id="get-started-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "get-started-btn":
            self.app.push_screen("dashboard")
