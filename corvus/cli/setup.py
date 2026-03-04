"""Claw setup CLI — Textual TUI entrypoint."""

import sys

from textual.app import App

from corvus.cli.screens.backends import ModelBackendsScreen
from corvus.cli.screens.complete import CompleteScreen
from corvus.cli.screens.passphrase import PassphraseScreen
from corvus.cli.screens.services import ServicesScreen
from corvus.cli.screens.welcome import WelcomeScreen


class ClawSetupApp(App):
    """Claw setup wizard — multi-screen TUI."""

    TITLE = "Claw Setup"
    CSS = """
    Screen {
        align: center middle;
    }
    #title {
        text-style: bold;
        color: $accent;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #description {
        text-align: center;
        width: 60;
        margin-bottom: 1;
    }
    Button {
        margin: 1 2;
    }
    """

    SCREENS = {
        "welcome": WelcomeScreen,
        "backends": ModelBackendsScreen,
        "services": ServicesScreen,
        "passphrase": PassphraseScreen,
        "complete": CompleteScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("welcome")

    def _save_credentials(self) -> None:
        """Save collected credentials to the CredentialStore."""
        from pathlib import Path

        from corvus.break_glass import BreakGlassManager
        from corvus.credential_store import CredentialStore

        config_dir = Path.home() / ".corvus"
        config_dir.mkdir(parents=True, exist_ok=True)

        age_key_file = config_dir / "age-key.txt"
        if not age_key_file.exists():
            import subprocess

            subprocess.run(
                ["age-keygen", "-o", str(age_key_file)],
                capture_output=True,
                check=True,
            )
            age_key_file.chmod(0o600)

        store = CredentialStore(
            path=config_dir / "credentials.json",
            age_key_file=str(age_key_file),
        )

        # Save LLM backend credentials
        backends_data = getattr(self, "_backends_data", {})

        # Map wizard field names to credential store keys
        backend_key_map = {
            "claude": {"api-key": "api_key"},
            "openai": {"api-key": "api_key"},
            "ollama": {"base-url": "base_url"},
            "kimi": {"api-key": "api_key"},
            "openai-compat": {
                "label": "label",
                "base-url": "base_url",
                "api-key": "api_key",
            },
        }

        for backend_id, fields in backends_data.items():
            # Store under "anthropic" for Claude to keep backward compat with inject()
            store_key = "anthropic" if backend_id == "claude" else backend_id
            key_map = backend_key_map.get(backend_id, {})
            for field_key, value in fields.items():
                cred_key = key_map.get(field_key, field_key)
                store.set(store_key, cred_key, value)

        # Save service credentials
        if hasattr(self, "_services_data"):
            for svc_id, svc_data in self._services_data.items():
                for key, value in svc_data.items():
                    store.set(svc_id, key, value)

        if getattr(self, "_passphrase_set", False) and hasattr(self, "_passphrase"):
            mgr = BreakGlassManager(config_dir=config_dir)
            mgr.set_passphrase(self._passphrase)


def main() -> None:
    """CLI entrypoint for setup wizard."""
    args = sys.argv[1:]
    if not args:
        app = ClawSetupApp()
        app.run()
    elif args[0] == "status":
        from corvus.cli.screens.status import StatusScreen

        class StatusApp(App):
            TITLE = "Claw Status"
            CSS = ClawSetupApp.CSS
            SCREENS = {"status": StatusScreen}

            def on_mount(self) -> None:
                self.push_screen("status")

        StatusApp().run()
    elif args[0] == "add":
        print("Add credential not yet implemented")
    elif args[0] == "rotate":
        print("Rotate credential not yet implemented")
    elif args[0] == "passphrase":
        print("Passphrase management not yet implemented")
    else:
        print(f"Unknown command: {args[0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
