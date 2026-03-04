"""Break-glass passphrase setup screen.

Two password inputs with match checking and strength indicator via zxcvbn.
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Static

MIN_LENGTH = 12
MIN_ZXCVBN_SCORE = 3


def _check_strength(passphrase: str) -> tuple[int, str]:
    """Check passphrase strength with zxcvbn. Returns (score, description)."""
    if not passphrase:
        return 0, ""
    try:
        from zxcvbn import zxcvbn

        result = zxcvbn(passphrase)
        score = result["score"]
        labels = ["Very Weak", "Weak", "Fair", "Strong", "Very Strong"]
        return score, labels[score]
    except ImportError:
        if len(passphrase) >= 16:
            return 4, "Strong (length-based)"
        return 2, "Fair (install zxcvbn for better scoring)"


class PassphraseScreen(Screen):
    """Passphrase input with strength checking and confirmation."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("BREAK-GLASS PASSPHRASE", id="title")
        yield Static("\nSet a passphrase for emergency access:\n")
        yield Input(
            placeholder="Passphrase (min 12 chars)",
            id="passphrase-input",
            password=True,
        )
        yield Static("", id="strength-label")
        yield Static("\nConfirm:")
        yield Input(placeholder="Confirm passphrase", id="confirm-input", password=True)
        yield Static("", id="match-label")
        yield Button("\u2190 Back", id="back-btn")
        yield Button("Finish", id="finish-btn", variant="primary", disabled=True)
        yield Button("Skip", id="skip-btn", variant="warning")

    def _update_finish_state(self) -> None:
        """Enable Finish only when passphrase is strong enough and matches."""
        pw = self.query_one("#passphrase-input", Input).value
        confirm = self.query_one("#confirm-input", Input).value
        score, _ = _check_strength(pw)
        matches = pw == confirm and len(pw) > 0
        strong_enough = len(pw) >= MIN_LENGTH and score >= MIN_ZXCVBN_SCORE

        match_label = self.query_one("#match-label", Static)
        if matches and pw:
            match_label.update("Match")
        elif confirm:
            match_label.update("Mismatch")
        else:
            match_label.update("")

        self.query_one("#finish-btn", Button).disabled = not (matches and strong_enough)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "passphrase-input":
            score, label = _check_strength(event.value)
            self.query_one("#strength-label", Static).update(f"Strength: {label}" if label else "")
        self._update_finish_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "skip-btn":
            self.app._passphrase_set = False  # type: ignore[attr-defined]
            self.app.push_screen("complete")
        elif event.button.id == "finish-btn":
            passphrase = self.query_one("#passphrase-input", Input).value
            self.app._passphrase = passphrase  # type: ignore[attr-defined]
            self.app._passphrase_set = True  # type: ignore[attr-defined]
            self.app.push_screen("complete")
