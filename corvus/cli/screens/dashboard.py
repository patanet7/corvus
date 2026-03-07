"""Dashboard screen — main credential management interface.

Shows all providers in two sections (LLM Backends, Services) with
status indicators, masked credential values, and edit/setup buttons.
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Label, Static

from corvus.auth.health_monitor import get_all_profile_health
from corvus.auth.profiles import AuthProfileStore
from corvus.break_glass import BreakGlassManager
from corvus.cli.screens.custom_modal import CustomModal
from corvus.cli.screens.oauth_modal import OAuthModal
from corvus.cli.screens.provider_modal import ProviderModal
from corvus.credential_store import mask_value

# Provider definitions: (id, label, auth_type, fields)
# auth_type: "api_key", "url", "url_key", "oauth", "claude_multi"
# fields: list of (field_key, placeholder, is_password)

LLM_BACKENDS = [
    ("claude", "Anthropic Claude", "claude_multi", [
        ("api_key", "API key (sk-ant-...)", True),
        ("setup_token", "Setup token (from claude setup-token)", True),
    ]),
    ("openai", "OpenAI", "api_key", [
        ("api_key", "API key (sk-...)", True),
    ]),
    ("codex", "Codex (ChatGPT)", "oauth", []),
    ("ollama", "Ollama (local)", "url", [
        ("base_url", "Base URL", False),
    ]),
    ("kimi", "Kimi / Moonshot", "api_key", [
        ("api_key", "API key", True),
    ]),
    ("openai_compat", "OpenAI-compatible", "url_key", [
        ("base_url", "Base URL", False),
        ("api_key", "API key (optional)", True),
    ]),
]

SERVICES = [
    ("ha", "Home Assistant", "url_key", [
        ("url", "URL (https://...)", False),
        ("token", "Long-lived access token", True),
    ]),
    ("paperless", "Paperless", "url_key", [
        ("url", "URL (https://...)", False),
        ("token", "API token", True),
    ]),
    ("firefly", "Firefly III", "url_key", [
        ("url", "URL (https://...)", False),
        ("token", "API token", True),
    ]),
    ("obsidian", "Obsidian", "url_key", [
        ("url", "URL (https://...)", False),
        ("token", "API token", True),
    ]),
]


class ProviderRow(Widget):
    """A single provider row with status dot, label, masked value, and action button."""

    DEFAULT_CSS = """
    ProviderRow {
        layout: horizontal;
        height: 3;
        padding: 0 1;
    }
    ProviderRow .status-dot {
        width: 3;
        color: $success;
    }
    ProviderRow .status-dot.dim {
        color: $text-muted;
    }
    ProviderRow .provider-label {
        width: 20;
    }
    ProviderRow .provider-value {
        width: 1fr;
        color: $text-muted;
    }
    ProviderRow .provider-value.configured {
        color: $text;
    }
    """

    def __init__(
        self,
        provider_id: str,
        label: str,
        status: str = "not_configured",
        masked_value: str = "",
        auth_type: str = "api_key",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.label = label
        self.status = status
        self.masked_value = masked_value
        self.auth_type = auth_type

    def compose(self) -> ComposeResult:
        is_configured = self.status in ("configured", "authenticated")
        dot = "\u25cf" if is_configured else "\u25cb"
        dot_class = "status-dot" if is_configured else "status-dot dim"
        value_class = "provider-value configured" if is_configured else "provider-value"

        display_value = self.masked_value if is_configured else "not configured"
        button_label = "Edit" if is_configured else "Setup"
        if self.auth_type == "oauth" and is_configured:
            button_label = "Re-auth"

        yield Label(dot, classes=dot_class)
        yield Label(self.label, classes="provider-label")
        yield Label(display_value, classes=value_class)
        yield Button(button_label, id=f"btn-{self.provider_id}", variant="default")


class DashboardScreen(Screen):
    """Main credential management dashboard."""

    BINDINGS = [
        ("q", "app.quit", "Quit"),
        ("escape", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #dashboard-content {
        padding: 1 2;
    }
    .section-header {
        text-style: bold;
        color: $accent;
        margin: 1 0 0 0;
    }
    .section-panel {
        border: round $primary;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    .passphrase-row {
        layout: horizontal;
        height: 3;
        padding: 0 1;
        margin: 1 0;
    }
    #btn-save-exit {
        margin: 1 2;
        width: auto;
    }
    #btn-add-provider, #btn-add-service {
        margin: 0 1;
    }
    """

    def __init__(self, credential_data: dict | None = None, auth_profiles: AuthProfileStore | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._credential_data = credential_data or {}
        self._auth_profiles = auth_profiles or AuthProfileStore()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="dashboard-content"):
            yield Static("LLM Backends", classes="section-header")
            with Vertical(classes="section-panel"):
                for pid, label, auth_type, fields in LLM_BACKENDS:
                    status, masked = self._get_provider_status(pid, auth_type, fields)
                    yield ProviderRow(
                        provider_id=pid,
                        label=label,
                        status=status,
                        masked_value=masked,
                        auth_type=auth_type,
                        id=f"row-{pid}",
                    )
                yield Button("+ Add Provider", id="btn-add-provider", variant="default")

            yield Static("Services", classes="section-header")
            with Vertical(classes="section-panel"):
                for pid, label, auth_type, fields in SERVICES:
                    status, masked = self._get_provider_status(pid, auth_type, fields)
                    yield ProviderRow(
                        provider_id=pid,
                        label=label,
                        status=status,
                        masked_value=masked,
                        auth_type=auth_type,
                        id=f"row-{pid}",
                    )
                yield Button("+ Add Service", id="btn-add-service", variant="default")

            passphrase_status = self._get_passphrase_status()
            with Vertical(classes="passphrase-row"):
                yield Static(
                    f"Break-glass passphrase: {passphrase_status}",
                    id="passphrase-status",
                )
                yield Button(
                    "Change" if passphrase_status == "set" else "Set",
                    id="btn-passphrase",
                    variant="default",
                )

            yield Button("Save & Exit", id="btn-save-exit", variant="primary")
        yield Footer()

    def _get_provider_status(
        self,
        provider_id: str,
        auth_type: str,
        fields: list,
    ) -> tuple[str, str]:
        """Return (status, masked_display_value) for a provider."""
        # Check auth profiles first
        store_provider = "anthropic" if provider_id == "claude" else provider_id
        provider_profiles = {
            pid: cred for pid, cred in self._auth_profiles.profiles.items()
            if cred.provider == store_provider
        }
        if provider_profiles:
            health = get_all_profile_health(self._auth_profiles)
            healthy = sum(1 for pid in provider_profiles if health.get(pid) and health[pid].status == "healthy")
            total = len(provider_profiles)
            if healthy > 0:
                return "configured", f"{healthy}/{total} profiles"
            return "not_configured", f"0/{total} profiles"

        # Fall back to flat credential display
        svc_data = self._credential_data.get(provider_id, {})
        if provider_id == "claude":
            svc_data = self._credential_data.get("anthropic", {})

        if not svc_data:
            return "not_configured", ""

        if auth_type == "oauth":
            token = svc_data.get("access_token", "")
            if token:
                return "authenticated", "Authenticated"
            return "not_configured", ""

        for field_key, _, _ in fields:
            val = svc_data.get(field_key, "")
            if val:
                return "configured", mask_value(val)
        return "not_configured", ""

    def _get_passphrase_status(self) -> str:
        """Check if break-glass passphrase is set."""
        config_dir = Path.home() / ".corvus"
        mgr = BreakGlassManager(config_dir=config_dir)
        return "set" if mgr.has_passphrase() else "not set"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "btn-save-exit":
            self.app.exit()
        elif btn_id == "btn-passphrase":
            self.app.push_screen("passphrase")
        elif btn_id.startswith("btn-") and btn_id not in (
            "btn-add-provider",
            "btn-add-service",
            "btn-save-exit",
            "btn-passphrase",
        ):
            provider_id = btn_id.removeprefix("btn-")
            self._open_edit_modal(provider_id)
        elif btn_id == "btn-add-provider":
            self._open_custom_modal("provider")
        elif btn_id == "btn-add-service":
            self._open_custom_modal("service")

    def _open_edit_modal(self, provider_id: str) -> None:
        """Open the edit/setup modal for a provider."""
        all_providers = LLM_BACKENDS + SERVICES
        for pid, label, auth_type, fields in all_providers:
            if pid == provider_id:
                if auth_type == "oauth":
                    def _on_oauth_result(tokens, _pid=pid) -> None:
                        if tokens is not None:
                            self.app.save_oauth_tokens(_pid, tokens)
                            self._refresh_row(_pid, "authenticated", "Authenticated")

                    self.app.push_screen(
                        OAuthModal(provider_id=pid, label=label),
                        callback=_on_oauth_result,
                    )
                else:
                    store_key = "anthropic" if pid == "claude" else pid
                    existing = self._credential_data.get(store_key, {})

                    def _on_provider_result(result, _sk=store_key, _pid=pid, _fields=fields) -> None:
                        if result is not None:
                            self.app.save_provider_credentials(_sk, result)
                            first_val = next(
                                (result[k] for k, _, _ in _fields if result.get(k)),
                                "",
                            )
                            self._refresh_row(_pid, "configured", mask_value(first_val))

                    self.app.push_screen(
                        ProviderModal(
                            provider_id=pid,
                            store_key=store_key,
                            label=label,
                            fields=fields,
                            existing_data=existing,
                        ),
                        callback=_on_provider_result,
                    )
                return

    def _open_custom_modal(self, section: str) -> None:
        """Open the add custom provider/service modal."""
        def _on_custom_result(result) -> None:
            if result is not None:
                self.app.save_custom_provider(result)

        self.app.push_screen(
            CustomModal(section=section),
            callback=_on_custom_result,
        )

    def _refresh_row(self, provider_id: str, status: str, masked_value: str) -> None:
        """Update a provider row's display after save."""
        try:
            row = self.query_one(f"#row-{provider_id}", ProviderRow)
            row.status = status
            row.masked_value = masked_value
            row.refresh()
        except Exception:
            pass
