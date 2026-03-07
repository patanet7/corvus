# Setup Wizard Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 5-screen linear setup wizard with a dashboard-first credential management TUI that detects existing config, masks secrets, and saves per-provider.

**Architecture:** Single Textual app with two flows: first-run (Welcome -> Dashboard -> Break-glass) and re-run (Dashboard directly). Dashboard shows all providers in two sections (LLM Backends, Services) with edit modals. Each save is an atomic SOPS encrypt. Modern TUI styling with bordered panels, status dots, footer keybindings.

**Tech Stack:** Python 3.13, Textual 8.0.2, SOPS + age encryption, existing `CredentialStore` class

**Design doc:** `docs/plans/2026-03-07-setup-wizard-redesign.md`

**Project rules:**
- NO MOCKS in tests (no MagicMock, monkeypatch, @patch, unittest.mock)
- NO LAZY IMPORTS — all imports at module top
- NO RELATIVE IMPORTS — always `from corvus.x import y`
- Tests must be behavioral — exercise real code with real setup/teardown
- Use `uv run python` not bare `python3`
- Test output goes to `tests/output/` with timestamps

---

### Task 1: CredentialStore helpers — mask_value and set_bulk

**Files:**
- Modify: `corvus/credential_store.py`
- Create: `tests/unit/test_credential_store_helpers.py`

**Step 1: Write the failing tests**

```python
"""Tests for CredentialStore mask_value and set_bulk helpers."""

from corvus.credential_store import CredentialStore, mask_value


class TestMaskValue:
    """Tests for the mask_value utility function."""

    def test_masks_api_key(self) -> None:
        assert mask_value("sk-ant-api3abc123xyz") == "sk-ant-a..."

    def test_masks_short_value(self) -> None:
        """Values shorter than 8 chars get fully masked."""
        assert mask_value("short") == "..."

    def test_masks_url(self) -> None:
        assert mask_value("https://ha.local:8123/api") == "https://..."

    def test_empty_string(self) -> None:
        assert mask_value("") == ""

    def test_none_returns_empty(self) -> None:
        assert mask_value(None) == ""


class TestSetBulk:
    """Tests for set_bulk (batch write without per-key SOPS encrypt)."""

    def test_set_bulk_writes_multiple_keys(self, tmp_path) -> None:
        """set_bulk should write all keys then encrypt once."""
        # We can't test SOPS without real keys, so test the in-memory state
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}

        store.set_bulk("codex", {
            "access_token": "tok_abc",
            "refresh_token": "tok_ref",
            "expires": "999999",
        })

        assert store._data["codex"]["access_token"] == "tok_abc"
        assert store._data["codex"]["refresh_token"] == "tok_ref"
        assert store._data["codex"]["expires"] == "999999"

    def test_set_bulk_merges_with_existing(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {"codex": {"account_id": "acc_123"}}

        store.set_bulk("codex", {"access_token": "new_tok"})

        assert store._data["codex"]["account_id"] == "acc_123"
        assert store._data["codex"]["access_token"] == "new_tok"
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_credential_store_helpers.py -v`
Expected: FAIL — `mask_value` not found, `set_bulk` not found

**Step 3: Implement mask_value and set_bulk**

Add to `corvus/credential_store.py` — `mask_value` as a module-level function before the class, `set_bulk` as a method on `CredentialStore`:

```python
def mask_value(value: str | None, visible_chars: int = 8) -> str:
    """Mask a credential value for safe display.

    Shows the first *visible_chars* characters followed by '...'.
    Values shorter than *visible_chars* are fully masked.
    URLs are masked after the scheme (https://...).
    """
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        scheme_end = value.index("://") + 3
        return value[:scheme_end] + "..."
    if len(value) <= visible_chars:
        return "..."
    return value[:visible_chars] + "..."
```

And inside the `CredentialStore` class, after `set()`:

```python
def set_bulk(self, service: str, data: dict[str, str]) -> None:
    """Set multiple keys for a service with a single encrypt cycle."""
    if service not in self._data:
        self._data[service] = {}
    self._data[service].update(data)
    if self._path is not None:
        self._save()
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_credential_store_helpers.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add corvus/credential_store.py tests/unit/test_credential_store_helpers.py
git commit -m "feat: add mask_value and set_bulk to CredentialStore"
```

---

### Task 2: Dashboard screen — provider rows with status

This is the core screen. It renders two sections (LLM Backends, Services) with provider rows showing status dots, masked values, and action buttons.

**Files:**
- Create: `corvus/cli/screens/dashboard.py`
- Create: `tests/unit/test_setup_dashboard.py`

**Step 1: Write the failing tests**

```python
"""Behavioral tests for the setup dashboard screen."""

import asyncio

from textual.app import App, ComposeResult

from corvus.cli.screens.dashboard import DashboardScreen, ProviderRow


class DashboardTestApp(App):
    """Minimal app for testing the dashboard screen."""

    SCREENS = {"dashboard": DashboardScreen}

    def on_mount(self) -> None:
        self.push_screen("dashboard")


class TestProviderRow:
    """Tests for individual provider row rendering."""

    def test_configured_provider_shows_green_dot(self) -> None:
        row = ProviderRow(
            provider_id="claude",
            label="Anthropic Claude",
            status="configured",
            masked_value="sk-ant-a...",
        )
        assert row.status == "configured"
        assert row.masked_value == "sk-ant-a..."

    def test_unconfigured_provider_shows_dim(self) -> None:
        row = ProviderRow(
            provider_id="openai",
            label="OpenAI",
            status="not_configured",
            masked_value="",
        )
        assert row.status == "not_configured"

    def test_oauth_provider_shows_authenticated(self) -> None:
        row = ProviderRow(
            provider_id="codex",
            label="Codex (ChatGPT)",
            status="authenticated",
            masked_value="Authenticated",
        )
        assert row.status == "authenticated"


class TestDashboardScreen:
    """Tests for the full dashboard screen."""

    def test_dashboard_mounts_with_all_providers(self) -> None:
        app = DashboardTestApp()
        async def run_test() -> None:
            async with app.run_test() as pilot:
                screen = app.query_one(DashboardScreen)
                # Should have rows for all predefined providers
                rows = app.query(ProviderRow)
                provider_ids = [r.provider_id for r in rows]
                assert "claude" in provider_ids
                assert "openai" in provider_ids
                assert "codex" in provider_ids
                assert "ollama" in provider_ids
                assert "ha" in provider_ids
                assert "paperless" in provider_ids
        asyncio.run(run_test())

    def test_dashboard_shows_section_headers(self) -> None:
        app = DashboardTestApp()
        async def run_test() -> None:
            async with app.run_test() as pilot:
                text = app.query_one(DashboardScreen).render()
                # We verify section labels exist by querying widgets
                labels = [w for w in app.query("Static") if "LLM Backends" in str(w.renderable)]
                assert len(labels) >= 1
        asyncio.run(run_test())
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_setup_dashboard.py -v`
Expected: FAIL — `dashboard` module not found

**Step 3: Implement DashboardScreen**

Create `corvus/cli/screens/dashboard.py`:

```python
"""Dashboard screen — main credential management interface.

Shows all providers in two sections (LLM Backends, Services) with
status indicators, masked credential values, and edit/setup buttons.
"""

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Label, Static

from corvus.credential_store import mask_value

# Provider definitions: (id, label, section, auth_type, fields)
# auth_type: "api_key", "url", "url_key", "oauth"
# fields: list of (field_key, placeholder, is_password)

LLM_BACKENDS = [
    ("claude", "Anthropic Claude", "api_key", [
        ("api_key", "API key (sk-ant-...)", True),
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
        dot = "●" if is_configured else "○"
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

    def __init__(self, credential_data: dict | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._credential_data = credential_data or {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="dashboard-content"):
            # LLM Backends section
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

            # Services section
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

            # Break-glass row
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
        svc_data = self._credential_data.get(provider_id, {})
        # Map credential store keys: "claude" is stored as "anthropic"
        if provider_id == "claude":
            svc_data = self._credential_data.get("anthropic", {})

        if not svc_data:
            return "not_configured", ""

        if auth_type == "oauth":
            token = svc_data.get("access_token", "")
            if token:
                expires = svc_data.get("expires", "")
                if expires:
                    return "authenticated", "Authenticated"
                return "authenticated", "Authenticated"
            return "not_configured", ""

        # For non-OAuth: show first meaningful value masked
        for field_key, _, _ in fields:
            val = svc_data.get(field_key, "")
            if val:
                return "configured", mask_value(val)
        return "not_configured", ""

    def _get_passphrase_status(self) -> str:
        """Check if break-glass passphrase is set."""
        from pathlib import Path

        from corvus.break_glass import BreakGlassManager

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
        # Find provider definition
        all_providers = LLM_BACKENDS + SERVICES
        for pid, label, auth_type, fields in all_providers:
            if pid == provider_id:
                if auth_type == "oauth":
                    from corvus.cli.screens.oauth_modal import OAuthModal
                    self.app.push_screen(OAuthModal(provider_id=pid, label=label))
                else:
                    from corvus.cli.screens.provider_modal import ProviderModal
                    store_key = "anthropic" if pid == "claude" else pid
                    existing = self._credential_data.get(store_key, {})
                    self.app.push_screen(ProviderModal(
                        provider_id=pid,
                        store_key=store_key,
                        label=label,
                        fields=fields,
                        existing_data=existing,
                    ))
                return

    def _open_custom_modal(self, section: str) -> None:
        """Open the add custom provider/service modal."""
        from corvus.cli.screens.custom_modal import CustomModal
        self.app.push_screen(CustomModal(section=section))
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_setup_dashboard.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/dashboard.py tests/unit/test_setup_dashboard.py
git commit -m "feat: add dashboard screen with provider rows and sections"
```

---

### Task 3: Provider edit modal

Modal dialog for editing text-field providers (API keys, URLs, tokens). Shows masked existing value, password input for new value, save/cancel buttons.

**Files:**
- Create: `corvus/cli/screens/provider_modal.py`
- Create: `tests/unit/test_provider_modal.py`

**Step 1: Write the failing test**

```python
"""Behavioral tests for the provider edit modal."""

import asyncio

from textual.app import App

from corvus.cli.screens.provider_modal import ProviderModal


class TestProviderModal:
    """Tests for provider edit modal rendering."""

    def test_modal_renders_with_label(self) -> None:
        modal = ProviderModal(
            provider_id="claude",
            store_key="anthropic",
            label="Anthropic Claude",
            fields=[("api_key", "API key (sk-ant-...)", True)],
            existing_data={},
        )
        assert modal.label == "Anthropic Claude"
        assert modal.provider_id == "claude"

    def test_modal_shows_existing_masked_value(self) -> None:
        modal = ProviderModal(
            provider_id="claude",
            store_key="anthropic",
            label="Anthropic Claude",
            fields=[("api_key", "API key (sk-ant-...)", True)],
            existing_data={"api_key": "sk-ant-api3abc123xyz789"},
        )
        assert modal.existing_data["api_key"] == "sk-ant-api3abc123xyz789"
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_provider_modal.py -v`
Expected: FAIL — module not found

**Step 3: Implement ProviderModal**

Create `corvus/cli/screens/provider_modal.py`:

```python
"""Provider edit/setup modal — text-field credential input.

Shows a modal dialog with password inputs for each field,
masked existing values as hints, and save/cancel buttons.
Saves immediately to the credential store on confirm.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from corvus.credential_store import mask_value


class ProviderModal(ModalScreen[dict[str, str] | None]):
    """Modal for editing a provider's credentials."""

    DEFAULT_CSS = """
    ProviderModal {
        align: center middle;
    }
    #modal-container {
        width: 60;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #modal-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .field-hint {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    .field-input {
        margin-bottom: 1;
    }
    .modal-buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        provider_id: str,
        store_key: str,
        label: str,
        fields: list[tuple[str, str, bool]],
        existing_data: dict[str, str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.store_key = store_key
        self.label = label
        self.fields = fields
        self.existing_data = existing_data

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static(f"Configure {self.label}", id="modal-title")

            for field_key, placeholder, is_password in self.fields:
                existing = self.existing_data.get(field_key, "")
                yield Label(placeholder)
                yield Input(
                    placeholder=placeholder,
                    id=f"input-{field_key}",
                    password=is_password,
                    classes="field-input",
                )
                if existing:
                    yield Static(
                        f"Current: {mask_value(existing)}",
                        classes="field-hint",
                    )
                    yield Static(
                        "Leave blank to keep existing.",
                        classes="field-hint",
                    )

            with Vertical(classes="modal-buttons"):
                yield Button("Cancel", id="modal-cancel", variant="default")
                yield Button("Save", id="modal-save", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-cancel":
            self.dismiss(None)
        elif event.button.id == "modal-save":
            result: dict[str, str] = {}
            for field_key, _, _ in self.fields:
                inp = self.query_one(f"#input-{field_key}", Input)
                if inp.value:
                    result[field_key] = inp.value
                elif field_key in self.existing_data:
                    result[field_key] = self.existing_data[field_key]
            self.dismiss(result)
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_provider_modal.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/provider_modal.py tests/unit/test_provider_modal.py
git commit -m "feat: add provider edit modal with masked existing values"
```

---

### Task 4: OAuth modal for Codex

Modal for OAuth-based providers (Codex, potentially Claude Code). Shows auth status, "Sign in" button that triggers the PKCE flow.

**Files:**
- Create: `corvus/cli/screens/oauth_modal.py`
- Create: `tests/unit/test_oauth_modal.py`

**Step 1: Write the failing test**

```python
"""Behavioral tests for OAuth provider modal."""

from corvus.cli.screens.oauth_modal import OAuthModal


class TestOAuthModal:
    def test_modal_has_provider_id(self) -> None:
        modal = OAuthModal(provider_id="codex", label="Codex (ChatGPT)")
        assert modal.provider_id == "codex"

    def test_modal_has_label(self) -> None:
        modal = OAuthModal(provider_id="codex", label="Codex (ChatGPT)")
        assert modal.label == "Codex (ChatGPT)"
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_oauth_modal.py -v`
Expected: FAIL

**Step 3: Implement OAuthModal**

Create `corvus/cli/screens/oauth_modal.py`:

```python
"""OAuth modal — browser-based authentication for Codex/ChatGPT.

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
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_oauth_modal.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/oauth_modal.py tests/unit/test_oauth_modal.py
git commit -m "feat: add OAuth modal for Codex browser-based auth"
```

---

### Task 5: Custom provider modal

Modal for adding arbitrary providers/services with a name and key/value fields.

**Files:**
- Create: `corvus/cli/screens/custom_modal.py`
- Create: `tests/unit/test_custom_modal.py`

**Step 1: Write the failing test**

```python
"""Behavioral tests for custom provider modal."""

from corvus.cli.screens.custom_modal import CustomModal


class TestCustomModal:
    def test_modal_has_section(self) -> None:
        modal = CustomModal(section="provider")
        assert modal.section == "provider"

    def test_modal_accepts_service_section(self) -> None:
        modal = CustomModal(section="service")
        assert modal.section == "service"
```

**Step 2: Run test, verify fail**

Run: `uv run python -m pytest tests/unit/test_custom_modal.py -v`

**Step 3: Implement CustomModal**

Create `corvus/cli/screens/custom_modal.py`:

```python
"""Custom provider/service modal — add arbitrary credentials.

Allows adding a new provider or service with a user-defined name
and key/value pairs.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class CustomModal(ModalScreen[dict[str, str] | None]):
    """Modal for adding a custom provider or service."""

    DEFAULT_CSS = """
    CustomModal {
        align: center middle;
    }
    #custom-container {
        width: 60;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #custom-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .custom-field {
        layout: horizontal;
        height: 3;
        margin-bottom: 1;
    }
    .custom-field Input {
        width: 1fr;
    }
    .custom-buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    .custom-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, section: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.section = section
        self._field_count = 1

    def compose(self) -> ComposeResult:
        title = "Add Custom Provider" if self.section == "provider" else "Add Custom Service"
        with Vertical(id="custom-container"):
            yield Static(title, id="custom-title")

            yield Label("Name")
            yield Input(placeholder="e.g. my-service", id="custom-name")

            yield Static("Fields:", classes="section-label")
            with Vertical(id="custom-fields"):
                yield self._make_field_row(1)

            yield Button("+ Add Field", id="custom-add-field", variant="default")

            with Vertical(classes="custom-buttons"):
                yield Button("Cancel", id="custom-cancel", variant="default")
                yield Button("Save", id="custom-save", variant="primary")

    def _make_field_row(self, index: int) -> Vertical:
        row = Vertical(classes="custom-field", id=f"field-row-{index}")
        row.compose_add_child(Input(placeholder="Key", id=f"custom-key-{index}"))
        row.compose_add_child(Input(placeholder="Value", id=f"custom-val-{index}", password=True))
        return row

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "custom-cancel":
            self.dismiss(None)
        elif event.button.id == "custom-add-field":
            self._field_count += 1
            container = self.query_one("#custom-fields")
            container.mount(self._make_field_row(self._field_count))
        elif event.button.id == "custom-save":
            name = self.query_one("#custom-name", Input).value.strip()
            if not name:
                return
            result: dict[str, str] = {"_name": name, "_section": self.section}
            for i in range(1, self._field_count + 1):
                try:
                    key_input = self.query_one(f"#custom-key-{i}", Input)
                    val_input = self.query_one(f"#custom-val-{i}", Input)
                    if key_input.value and val_input.value:
                        result[key_input.value] = val_input.value
                except Exception:
                    continue
            self.dismiss(result)
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_custom_modal.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/custom_modal.py tests/unit/test_custom_modal.py
git commit -m "feat: add custom provider/service modal"
```

---

### Task 6: Welcome screen rewrite with key backup

Rewrite the welcome screen to show the age public key for backup and generate the keypair if it doesn't exist.

**Files:**
- Modify: `corvus/cli/screens/welcome.py`
- Create: `tests/unit/test_welcome_screen.py`

**Step 1: Write the failing test**

```python
"""Behavioral tests for the welcome screen."""

import subprocess

from corvus.cli.screens.welcome import get_or_create_age_keypair


class TestGetOrCreateAgeKeypair:
    def test_creates_keypair_if_missing(self, tmp_path) -> None:
        key_file = tmp_path / "age-key.txt"
        public_key = get_or_create_age_keypair(key_file)
        assert public_key.startswith("age1")
        assert key_file.exists()
        assert oct(key_file.stat().st_mode)[-3:] == "600"

    def test_reads_existing_keypair(self, tmp_path) -> None:
        key_file = tmp_path / "age-key.txt"
        # Generate a real keypair first
        subprocess.run(
            ["age-keygen", "-o", str(key_file)],
            capture_output=True,
            check=True,
        )
        key_file.chmod(0o600)
        public_key = get_or_create_age_keypair(key_file)
        assert public_key.startswith("age1")
```

**Step 2: Run test, verify fail**

Run: `uv run python -m pytest tests/unit/test_welcome_screen.py -v`
Expected: FAIL — `get_or_create_age_keypair` not found

**Step 3: Rewrite welcome.py**

```python
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
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_welcome_screen.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/welcome.py tests/unit/test_welcome_screen.py
git commit -m "feat: rewrite welcome screen with age key backup display"
```

---

### Task 7: Setup app rewrite — first-run detection and routing

Rewrite `setup.py` to detect first-run vs re-run, load existing credentials, and route to the correct flow. Wire up modals to persist credentials on save.

**Files:**
- Modify: `corvus/cli/setup.py`
- Create: `tests/unit/test_setup_app.py`

**Step 1: Write the failing test**

```python
"""Behavioral tests for setup app routing."""

from pathlib import Path

from corvus.cli.setup import is_first_run


class TestIsFirstRun:
    def test_first_run_when_no_credentials(self, tmp_path) -> None:
        assert is_first_run(config_dir=tmp_path) is True

    def test_not_first_run_when_credentials_exist(self, tmp_path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text("{}")
        assert is_first_run(config_dir=tmp_path) is False
```

**Step 2: Run test, verify fail**

Run: `uv run python -m pytest tests/unit/test_setup_app.py -v`

**Step 3: Rewrite setup.py**

```python
"""Corvus setup CLI — Textual TUI entrypoint.

First run: Welcome (key backup) -> Dashboard -> Break-glass
Re-run: Dashboard (populated with existing credentials, masked)
"""

import sys
from pathlib import Path

from textual.app import App

from corvus.cli.screens.custom_modal import CustomModal
from corvus.cli.screens.dashboard import DashboardScreen
from corvus.cli.screens.oauth_modal import OAuthModal
from corvus.cli.screens.passphrase import PassphraseScreen
from corvus.cli.screens.provider_modal import ProviderModal
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
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_setup_app.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/setup.py tests/unit/test_setup_app.py
git commit -m "feat: rewrite setup app with first-run detection and credential persistence"
```

---

### Task 8: Wire up modal callbacks to credential store

Connect the dashboard's modals so that when a user saves, credentials are persisted to the SOPS store and the dashboard row updates.

**Files:**
- Modify: `corvus/cli/screens/dashboard.py` — add modal callback handling
- Modify: `corvus/cli/setup.py` — ensure `save_provider_credentials` is called from modal results

**Step 1: Add callback wiring to DashboardScreen**

In `dashboard.py`, update `_open_edit_modal` to handle the modal result callback:

```python
def _open_edit_modal(self, provider_id: str) -> None:
    all_providers = LLM_BACKENDS + SERVICES
    for pid, label, auth_type, fields in all_providers:
        if pid == provider_id:
            if auth_type == "oauth":
                def _on_oauth_result(tokens) -> None:
                    if tokens is not None:
                        self.app.save_oauth_tokens(pid, tokens)
                        self._refresh_row(pid, "authenticated", "Authenticated")

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
                        from corvus.credential_store import mask_value
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
    def _on_custom_result(result) -> None:
        if result is not None:
            self.app.save_custom_provider(result)
            # TODO: dynamically add row to dashboard

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
        # Force re-render by refreshing the row
        row.refresh()
    except Exception:
        pass
```

**Step 2: Test the full flow manually**

Run: `uv run python -m corvus.cli.setup`

Verify:
1. First run shows welcome screen with age key
2. Dashboard shows all providers
3. Click "Setup" on any provider → modal opens
4. Enter a value → click Save → row updates to show masked value
5. Re-run → dashboard shows previously saved values masked

**Step 3: Commit**

```bash
git add corvus/cli/screens/dashboard.py corvus/cli/setup.py
git commit -m "feat: wire modal callbacks to credential store persistence"
```

---

### Task 9: Delete old screens and update imports

Remove the old screens that the dashboard replaces. Update any imports.

**Files:**
- Delete: `corvus/cli/screens/backends.py`
- Delete: `corvus/cli/screens/services.py`
- Delete: `corvus/cli/screens/complete.py`
- Delete: `corvus/cli/screens/status.py`
- Modify: `corvus/cli/screens/__init__.py`
- Delete old tests if any reference deleted screens

**Step 1: Check for imports of deleted modules**

Run: `uv run ruff check corvus/ tests/ 2>&1` to find broken imports after deletion.

Search for references:
```bash
grep -r "from corvus.cli.screens.backends" corvus/ tests/
grep -r "from corvus.cli.screens.services" corvus/ tests/
grep -r "from corvus.cli.screens.complete" corvus/ tests/
grep -r "from corvus.cli.screens.status" corvus/ tests/
```

**Step 2: Delete the files**

```bash
rm corvus/cli/screens/backends.py
rm corvus/cli/screens/services.py
rm corvus/cli/screens/complete.py
rm corvus/cli/screens/status.py
```

**Step 3: Fix any broken imports found in step 1**

The main one will be in `corvus/cli/setup.py` — the old `ClawSetupApp` imported `ModelBackendsScreen`, `ServicesScreen`, `CompleteScreen`. The rewritten `setup.py` from Task 7 already uses the new imports, so this should be clean.

**Step 4: Run full test suite**

Run: `uv run python -m pytest tests/unit/ -v --timeout=30`
Expected: All tests pass. Any tests referencing deleted screens should also be removed.

**Step 5: Run lint**

Run: `uv run ruff check corvus/ tests/`
Expected: Clean

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove old wizard screens replaced by dashboard"
```

---

### Task 10: Styling polish and passphrase screen update

Apply consistent modern TUI styling across all screens. Update passphrase screen to match the new visual style.

**Files:**
- Modify: `corvus/cli/setup.py` — app-level CSS
- Modify: `corvus/cli/screens/passphrase.py` — visual styling update
- Modify: `corvus/cli/screens/dashboard.py` — final styling tweaks

**Step 1: Add app-level CSS to CorvusSetupApp**

In `corvus/cli/setup.py`, expand the CSS:

```python
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
```

**Step 2: Update passphrase screen styling**

Add `DEFAULT_CSS` to `PassphraseScreen` with borders and proper spacing to match the dashboard style.

**Step 3: Run the app visually**

Run: `uv run python -m corvus.cli.setup`

Verify the look matches the design doc mockup: bordered panels, green/dim dots, clean spacing, footer keybindings.

**Step 4: Commit**

```bash
git add corvus/cli/setup.py corvus/cli/screens/passphrase.py corvus/cli/screens/dashboard.py
git commit -m "style: polish TUI styling across all setup screens"
```

---

### Task 11: Full test suite verification and cleanup

Run all tests, fix any failures, lint, and verify the complete setup flow works end-to-end.

**Files:**
- All test files from previous tasks
- Any fixes needed

**Step 1: Run full test suite**

```bash
uv run python -m pytest tests/unit/ -v --timeout=30 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_setup_wizard_results.log
```

Expected: All tests pass

**Step 2: Run lint**

```bash
uv run ruff check corvus/ tests/
```

Expected: Clean

**Step 3: Manual end-to-end test**

1. Delete `~/.corvus/credentials.json` (back up first!)
2. Run `uv run python -m corvus.cli.setup`
3. Verify: welcome screen with age key → get started → dashboard (all unconfigured)
4. Setup a provider → verify it saves → re-run → verify it's shown masked
5. Run `mise run setup:status` → verify dashboard shows current state

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test: verify full setup wizard test suite and cleanup"
```
