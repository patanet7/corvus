"""OAuth modal -- browser-based authentication for Codex/ChatGPT.

Opens browser for PKCE OAuth flow, captures callback, stores tokens.
"""

import webbrowser
from threading import Thread

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from corvus.auth.openai_oauth import (
    OAuthTokens,
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce,
    run_callback_server,
)


class OAuthModal(ModalScreen[OAuthTokens | None]):
    """Modal for OAuth-based provider authentication."""

    DEFAULT_CSS = """
    OAuthModal {
        align: center middle;
    }
    #oauth-container {
        width: 55;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #oauth-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #oauth-status {
        margin: 1 0;
    }
    .oauth-buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    .oauth-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, provider_id: str, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="oauth-container"):
            yield Static(f"{self.label}", id="oauth-title")
            yield Static(
                "Opens your browser for authentication.\n"
                "Tokens are stored encrypted in your local credential store.",
            )
            yield Static("", id="oauth-status")
            yield Button(
                "Sign in with ChatGPT",
                id="oauth-sign-in",
                variant="success",
            )
            with Vertical(classes="oauth-buttons"):
                yield Button("Cancel", id="oauth-cancel", variant="default")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "oauth-cancel":
            self.dismiss(None)
        elif event.button.id == "oauth-sign-in":
            self._run_oauth()

    def _run_oauth(self) -> None:
        status = self.query_one("#oauth-status", Static)
        status.update("Starting OAuth flow...")
        sign_in_btn = self.query_one("#oauth-sign-in", Button)
        sign_in_btn.disabled = True

        pkce = generate_pkce()
        server, get_result = run_callback_server()

        def _flow() -> None:
            url = build_authorize_url(pkce)
            webbrowser.open(url)
            server.handle_request()
            server.server_close()
            result = get_result()
            if result.get("code") and result.get("state") == pkce.state:
                try:
                    tokens = exchange_code_for_tokens(
                        code=result["code"],
                        verifier=pkce.verifier,
                    )
                    self.app.call_from_thread(status.update, "Authenticated!")
                    self.app.call_from_thread(self.dismiss, tokens)
                except Exception as exc:
                    self.app.call_from_thread(
                        status.update, f"OAuth failed: {exc}"
                    )
                    self.app.call_from_thread(sign_in_btn.__setattr__, "disabled", False)
            else:
                self.app.call_from_thread(
                    status.update, "Failed: state mismatch or missing code"
                )
                self.app.call_from_thread(sign_in_btn.__setattr__, "disabled", False)

        Thread(target=_flow, daemon=True).start()
