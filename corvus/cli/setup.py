"""Corvus setup CLI — Textual TUI entrypoint.

First run: Welcome (key backup) -> Dashboard -> Break-glass
Re-run: Dashboard (populated with existing credentials, masked)
"""

import sys
from pathlib import Path

from textual.app import App

from corvus.cli.screens.dashboard import DashboardScreen
from corvus.cli.screens.passphrase import PassphraseScreen
from corvus.cli.screens.welcome import WelcomeScreen
from corvus.credential_store import CredentialStore


def is_first_run(config_dir: Path | None = None) -> bool:
    """Check if this is the first time setup is being run."""
    config_dir = config_dir or Path.home() / ".corvus"
    return not (config_dir / "credentials.json").exists()


class CorvusSetupApp(App):
    """Corvus setup — dashboard-first credential management."""

    TITLE = "Corvus Setup"

    CSS = """
    Screen {
        background: $surface;
    }
    Header {
        dock: top;
        background: $primary;
    }
    Footer {
        dock: bottom;
    }
    Button {
        margin: 0 1;
    }
    Button.-primary {
        background: $primary;
    }
    .section-header {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 1;
    }
    .section-panel {
        border: round $primary;
        padding: 0 1;
        margin: 0 1 1 1;
    }
    """

    def __init__(self, config_dir: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config_dir = config_dir or Path.home() / ".corvus"
        self._store: CredentialStore | None = None
        self._credential_data: dict = {}

    def on_mount(self) -> None:
        creds_path = self._config_dir / "credentials.json"
        age_key = self._config_dir / "age-key.txt"

        if creds_path.exists() and age_key.exists():
            # Re-run: load existing credentials, go to dashboard
            try:
                self._store = CredentialStore(
                    path=creds_path,
                    age_key_file=str(age_key),
                )
                self._store.load()
                self._credential_data = self._store._data.copy()
            except Exception:
                self._credential_data = {}
            self._push_dashboard()
        else:
            # First run: show welcome screen
            self.install_screen(WelcomeScreen(), name="welcome")
            self.push_screen("welcome")

    def _push_dashboard(self) -> None:
        dashboard = DashboardScreen(credential_data=self._credential_data)
        self.install_screen(dashboard, name="dashboard")
        self.install_screen(PassphraseScreen(), name="passphrase")
        self.push_screen("dashboard")

    def _get_or_create_store(self) -> CredentialStore:
        """Get existing store or create a new one."""
        if self._store is not None:
            return self._store
        age_key = self._config_dir / "age-key.txt"
        self._store = CredentialStore(
            path=self._config_dir / "credentials.json",
            age_key_file=str(age_key),
        )
        return self._store

    def save_provider_credentials(
        self, store_key: str, data: dict[str, str]
    ) -> None:
        """Save credentials for a provider to the SOPS store."""
        store = self._get_or_create_store()
        store.set_bulk(store_key, data)
        self._credential_data[store_key] = data

    def save_oauth_tokens(self, provider_id: str, tokens) -> None:
        """Save OAuth tokens to the SOPS store."""
        store = self._get_or_create_store()
        store.set_bulk(provider_id, {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires": str(tokens.expires),
            "account_id": tokens.account_id,
        })
        self._credential_data[provider_id] = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires": str(tokens.expires),
            "account_id": tokens.account_id,
        }

    def save_custom_provider(self, data: dict[str, str]) -> None:
        """Save a custom provider/service to the SOPS store."""
        name = data.pop("_name", "")
        data.pop("_section", "")
        if not name:
            return
        store = self._get_or_create_store()
        store.set_bulk(name, data)
        self._credential_data[name] = data


def main() -> None:
    """CLI entrypoint for setup wizard."""
    args = sys.argv[1:]
    if not args:
        app = CorvusSetupApp()
        app.run()
    elif args[0] == "status":
        # Status is now the same as the dashboard
        app = CorvusSetupApp()
        app.run()
    else:
        print(f"Unknown command: {args[0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
