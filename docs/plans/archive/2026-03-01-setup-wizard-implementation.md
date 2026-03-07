# Setup Wizard Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-provider Anthropic setup wizard with a multi-backend ModelBackendsScreen supporting Claude, OpenAI, Ollama, Kimi, and OpenAI-compatible endpoints, plus graceful server degradation when no LLM is configured.

**Architecture:** The Textual TUI setup wizard gets a new `ModelBackendsScreen` replacing `AnthropicScreen`. Five toggleable backend sections collect connection details (URLs + API keys) stored via SOPS credential store. Server startup reads the credential store to determine active backends, probes Ollama if configured, and degrades gracefully when no LLM is available.

**Tech Stack:** Python 3.13, Textual (TUI), FastAPI, SOPS+age credential store, SQLite, httpx (Ollama probe)

**Design Doc:** `docs/plans/2026-03-01-setup-wizard-redesign.md`

---

### Task 1: Create ModelBackendsScreen

**Files:**
- Create: `corvus/cli/screens/backends.py`
- Reference: `corvus/cli/screens/anthropic.py` (for pattern), `corvus/cli/screens/services.py` (for layout pattern)

**Step 1: Write the failing test**

Create `tests/gateway/test_setup_backends.py`:

```python
"""Behavioral tests for ModelBackendsScreen — real Textual app pilot."""

import pytest
from textual.app import App

from corvus.cli.screens.backends import ModelBackendsScreen


class BackendsTestApp(App):
    SCREENS = {"backends": ModelBackendsScreen}

    def on_mount(self) -> None:
        self.push_screen("backends")


@pytest.fixture
def app():
    return BackendsTestApp()


@pytest.mark.asyncio
async def test_screen_renders_all_backends(app):
    """All five backend toggles should render."""
    async with app.run_test() as pilot:
        for backend_id in ("claude", "openai", "ollama", "kimi", "openai-compat"):
            toggle = app.query_one(f"#toggle-{backend_id}")
            assert toggle is not None


@pytest.mark.asyncio
async def test_all_toggles_off_by_default(app):
    """All backend toggles should be off by default."""
    async with app.run_test() as pilot:
        for backend_id in ("claude", "openai", "ollama", "kimi", "openai-compat"):
            toggle = app.query_one(f"#toggle-{backend_id}")
            assert toggle.value is False


@pytest.mark.asyncio
async def test_skip_all_button_exists(app):
    """Skip All button should be present and enabled."""
    async with app.run_test() as pilot:
        skip_btn = app.query_one("#skip-btn")
        assert skip_btn is not None
        assert skip_btn.disabled is False


@pytest.mark.asyncio
async def test_ollama_default_url(app):
    """Ollama URL should default to localhost:11434 when toggled on."""
    async with app.run_test() as pilot:
        toggle = app.query_one("#toggle-ollama")
        toggle.value = True
        await pilot.pause()
        url_input = app.query_one("#ollama-base-url")
        assert url_input.value == "http://localhost:11434"
```

**Step 2: Run test to verify it fails**

Run: `mise run test -- tests/gateway/test_setup_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_setup_backends_results.log`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.cli.screens.backends'`

**Step 3: Write the ModelBackendsScreen**

Create `corvus/cli/screens/backends.py`:

```python
"""Model backends configuration screen.

Five toggleable backend sections: Claude, OpenAI, Ollama, Kimi, OpenAI-compatible.
All toggles off by default. Each backend shows input fields when enabled.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Header, Input, Static

# (backend_id, display_label, fields_when_enabled)
# Each field: (field_id_suffix, placeholder, is_password, default_value)
BACKENDS = [
    ("claude", "Anthropic Claude", [
        ("api-key", "API key (sk-ant-...)", True, ""),
    ]),
    ("openai", "OpenAI", [
        ("api-key", "API key (sk-...)", True, ""),
    ]),
    ("ollama", "Ollama (local)", [
        ("base-url", "Base URL", False, "http://localhost:11434"),
    ]),
    ("kimi", "Kimi / Moonshot", [
        ("api-key", "API key", True, ""),
    ]),
    ("openai-compat", "OpenAI-compatible endpoint", [
        ("label", "Provider name (e.g. LM Studio)", False, ""),
        ("base-url", "Base URL", False, ""),
        ("api-key", "API key (optional)", True, ""),
    ]),
]


def _validate_backend(backend_id: str, fields: dict[str, str]) -> tuple[bool, str]:
    """Validate backend fields. Returns (is_valid, error_message)."""
    if backend_id == "claude":
        key = fields.get("api-key", "")
        if not key.startswith("sk-ant-"):
            return False, "Must start with sk-ant-"
        if len(key) < 80:
            return False, f"Too short ({len(key)} chars, need 80+)"
        return True, ""
    if backend_id == "openai":
        key = fields.get("api-key", "")
        if not key.startswith("sk-"):
            return False, "Must start with sk-"
        return True, ""
    if backend_id == "ollama":
        url = fields.get("base-url", "")
        if not url.startswith(("http://", "https://")):
            return False, "Must be an HTTP(S) URL"
        return True, ""
    if backend_id == "kimi":
        key = fields.get("api-key", "")
        if not key:
            return False, "API key required"
        return True, ""
    if backend_id == "openai-compat":
        url = fields.get("base-url", "")
        if not url.startswith(("http://", "https://")):
            return False, "Must be an HTTP(S) URL"
        return True, ""
    return True, ""


class ModelBackendsScreen(Screen):
    """Model backend configuration with toggleable sections."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("MODEL BACKENDS", id="title")
        yield Static(
            "\nEnable the LLM backends you want to use.\n"
            "All are optional — skip to configure later.\n"
        )

        for backend_id, label, fields in BACKENDS:
            with Vertical(id=f"backend-{backend_id}", classes="backend-section"):
                yield Checkbox(label, id=f"toggle-{backend_id}", value=False)
                with Vertical(
                    id=f"fields-{backend_id}", classes="backend-fields"
                ):
                    for field_suffix, placeholder, is_password, default in fields:
                        yield Input(
                            placeholder=placeholder,
                            id=f"{backend_id}-{field_suffix}",
                            password=is_password,
                            value=default,
                        )
                yield Static("", id=f"validation-{backend_id}")

        yield Button("\u2190 Back", id="back-btn")
        yield Button("Skip All \u2192", id="skip-btn", variant="warning")
        yield Button("Next \u2192", id="next-btn", variant="primary")

    def on_mount(self) -> None:
        """Hide all field containers initially."""
        for backend_id, _, _ in BACKENDS:
            self.query_one(f"#fields-{backend_id}").display = False

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Show/hide fields when a backend toggle changes."""
        checkbox_id = event.checkbox.id
        if not checkbox_id or not checkbox_id.startswith("toggle-"):
            return
        backend_id = checkbox_id.removeprefix("toggle-")
        fields_container = self.query_one(f"#fields-{backend_id}")
        fields_container.display = event.value

    def _collect_enabled_backends(self) -> dict[str, dict[str, str]]:
        """Collect field values from all enabled backends."""
        result: dict[str, dict[str, str]] = {}
        for backend_id, _, fields in BACKENDS:
            toggle = self.query_one(f"#toggle-{backend_id}", Checkbox)
            if not toggle.value:
                continue
            field_values: dict[str, str] = {}
            for field_suffix, _, _, _ in fields:
                inp = self.query_one(f"#{backend_id}-{field_suffix}", Input)
                if inp.value:
                    field_values[field_suffix] = inp.value
            if field_values:
                result[backend_id] = field_values
        return result

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "skip-btn":
            self.app._backends_data = {}
            self.app.push_screen("services")
        elif event.button.id == "next-btn":
            backends = self._collect_enabled_backends()
            # Validate enabled backends
            for backend_id, fields in backends.items():
                valid, msg = _validate_backend(backend_id, fields)
                if not valid:
                    label = self.query_one(f"#validation-{backend_id}", Static)
                    label.update(f"Error: {msg}")
                    return
            self.app._backends_data = backends
            self.app.push_screen("services")
```

**Step 4: Run test to verify it passes**

Run: `mise run test -- tests/gateway/test_setup_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_setup_backends_results.log`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/backends.py tests/gateway/test_setup_backends.py
git commit -m "feat(setup): add ModelBackendsScreen with 5 toggleable LLM backends"
```

---

### Task 2: Wire ModelBackendsScreen into setup wizard

**Files:**
- Modify: `corvus/cli/setup.py`
- Modify: `corvus/cli/screens/welcome.py`
- Delete: `corvus/cli/screens/anthropic.py`

**Step 1: Write the failing test**

Add to `tests/gateway/test_setup_backends.py`:

```python
from corvus.cli.setup import ClawSetupApp


@pytest.mark.asyncio
async def test_wizard_has_backends_screen():
    """Setup wizard should register backends screen, not anthropic."""
    app = ClawSetupApp()
    assert "backends" in app.SCREENS
    assert "anthropic" not in app.SCREENS
```

**Step 2: Run test to verify it fails**

Run: `mise run test -- tests/gateway/test_setup_backends.py::test_wizard_has_backends_screen -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_setup_wizard_results.log`
Expected: FAIL — `"anthropic"` is still in `SCREENS`

**Step 3: Update setup.py**

In `corvus/cli/setup.py`, replace the `AnthropicScreen` import and `SCREENS` entry:

```python
# OLD:
from corvus.cli.screens.anthropic import AnthropicScreen
# NEW:
from corvus.cli.screens.backends import ModelBackendsScreen
```

Update `SCREENS` dict:
```python
# OLD:
    SCREENS = {
        "welcome": WelcomeScreen,
        "anthropic": AnthropicScreen,
        ...
    }
# NEW:
    SCREENS = {
        "welcome": WelcomeScreen,
        "backends": ModelBackendsScreen,
        ...
    }
```

Update `_save_credentials` to handle `_backends_data` instead of just `_api_key`:

```python
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

    # Save break-glass passphrase
    if getattr(self, "_passphrase_set", False) and hasattr(self, "_passphrase"):
        mgr = BreakGlassManager(config_dir=config_dir)
        mgr.set_passphrase(self._passphrase)
```

**Step 4: Update welcome.py**

Change navigation target from `"anthropic"` to `"backends"`:

```python
# OLD:
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-btn":
            self.app.push_screen("anthropic")
# NEW:
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-btn":
            self.app.push_screen("backends")
```

**Step 5: Delete anthropic.py**

```bash
git rm corvus/cli/screens/anthropic.py
```

**Step 6: Run all tests**

Run: `mise run test -- tests/gateway/test_setup_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_setup_wiring_results.log`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add corvus/cli/setup.py corvus/cli/screens/welcome.py tests/gateway/test_setup_backends.py
git rm corvus/cli/screens/anthropic.py
git commit -m "feat(setup): wire ModelBackendsScreen, remove AnthropicScreen"
```

---

### Task 3: Update CompleteScreen for all backends

**Files:**
- Modify: `corvus/cli/screens/complete.py`

**Step 1: Write the failing test**

Add to `tests/gateway/test_setup_backends.py`:

```python
from corvus.cli.screens.complete import SERVICE_LABELS, BACKEND_LABELS


def test_complete_screen_has_all_backend_labels():
    """CompleteScreen should list all 5 backend labels."""
    assert "claude" in BACKEND_LABELS
    assert "openai" in BACKEND_LABELS
    assert "ollama" in BACKEND_LABELS
    assert "kimi" in BACKEND_LABELS
    assert "openai-compat" in BACKEND_LABELS
```

**Step 2: Run test to verify it fails**

Run: `mise run test -- tests/gateway/test_setup_backends.py::test_complete_screen_has_all_backend_labels -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_complete_screen_results.log`
Expected: FAIL — `ImportError: cannot import name 'BACKEND_LABELS'`

**Step 3: Update complete.py**

Replace the content of `corvus/cli/screens/complete.py`:

```python
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
            self.app._save_credentials()
            self.app.exit()
```

**Step 4: Run test to verify it passes**

Run: `mise run test -- tests/gateway/test_setup_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_complete_updated_results.log`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/cli/screens/complete.py tests/gateway/test_setup_backends.py
git commit -m "feat(setup): update CompleteScreen to show all 5 backends"
```

---

### Task 4: Update credential store inject() for new backends

**Files:**
- Modify: `corvus/credential_store.py`

**Step 1: Write the failing test**

Add to `tests/gateway/test_credential_store.py` (or create a focused test file):

Create `tests/gateway/test_credential_inject_backends.py`:

```python
"""Test inject() handles new backend keys (openai, ollama, kimi, openai_compat)."""

import os

import pytest


def test_inject_openai_sets_env(monkeypatch):
    """OpenAI API key should be set as OPENAI_API_KEY env var."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {"openai": {"api_key": "sk-test-openai-key"}}

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store.inject()
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-openai-key"


def test_inject_ollama_sets_env(monkeypatch):
    """Ollama base_url should be stored for model router to read."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {"ollama": {"base_url": "http://localhost:11434"}}

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    store.inject()
    assert os.environ.get("OLLAMA_BASE_URL") == "http://localhost:11434"


def test_inject_kimi_sets_env(monkeypatch):
    """Kimi API key should be set as KIMI_BOT_TOKEN env var."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {"kimi": {"api_key": "kimi-test-key"}}

    monkeypatch.delenv("KIMI_BOT_TOKEN", raising=False)
    store.inject()
    assert os.environ.get("KIMI_BOT_TOKEN") == "kimi-test-key"
```

Note: These tests use `monkeypatch` for env vars only (not mocking behavior) — env var manipulation is acceptable per project policy since we're testing real code with real state, just controlling the environment.

**Step 2: Run test to verify it fails**

Run: `mise run test -- tests/gateway/test_credential_inject_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_credential_inject_results.log`
Expected: FAIL — `inject()` doesn't handle openai/ollama/kimi keys

**Step 3: Update inject() in credential_store.py**

Add new backend handling to the `inject()` method in `corvus/credential_store.py`. Add these blocks after the existing Anthropic block (line ~133):

```python
        # OpenAI -- SDK reads from env var
        if "openai" in self._data:
            api_key = self._data["openai"].get("api_key")
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key

        # Ollama -- base URL for model router
        if "ollama" in self._data:
            base_url = self._data["ollama"].get("base_url")
            if base_url:
                os.environ["OLLAMA_BASE_URL"] = base_url

        # Kimi -- bot token
        if "kimi" in self._data:
            api_key = self._data["kimi"].get("api_key")
            if api_key:
                os.environ["KIMI_BOT_TOKEN"] = api_key

        # OpenAI-compatible -- base URL and optional key
        if "openai_compat" in self._data:
            compat = self._data["openai_compat"]
            if compat.get("base_url"):
                os.environ["OPENAI_COMPAT_BASE_URL"] = compat["base_url"]
            if compat.get("api_key"):
                os.environ["OPENAI_COMPAT_API_KEY"] = compat["api_key"]
```

Also update `from_env()` to add the new env var mappings:

```python
        env_map = {
            "ha": {"url": "HA_URL", "token": "HA_TOKEN"},
            "paperless": {"url": "PAPERLESS_URL", "token": "PAPERLESS_API_TOKEN"},
            "firefly": {"url": "FIREFLY_URL", "token": "FIREFLY_API_TOKEN"},
            "anthropic": {"api_key": "ANTHROPIC_API_KEY"},
            "openai": {"api_key": "OPENAI_API_KEY"},
            "ollama": {"base_url": "OLLAMA_BASE_URL"},
            "kimi": {"api_key": "KIMI_BOT_TOKEN"},
            "openai_compat": {
                "base_url": "OPENAI_COMPAT_BASE_URL",
                "api_key": "OPENAI_COMPAT_API_KEY",
            },
            "webhook_secret": {"value": "WEBHOOK_SECRET"},
        }
```

**Step 4: Run test to verify it passes**

Run: `mise run test -- tests/gateway/test_credential_inject_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_credential_inject_pass_results.log`
Expected: All 3 tests PASS

**Step 5: Run full credential store test suite**

Run: `mise run test -- tests/gateway/test_credential_store.py tests/gateway/test_credential_integration.py tests/gateway/test_credential_wiring.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_credential_full_results.log`
Expected: All existing tests still PASS

**Step 6: Commit**

```bash
git add corvus/credential_store.py tests/gateway/test_credential_inject_backends.py
git commit -m "feat(credentials): inject() supports openai, ollama, kimi, openai-compat backends"
```

---

### Task 5: Add Ollama probe at server startup

**Files:**
- Create: `corvus/ollama_probe.py`
- Modify: `corvus/server.py` (lifespan)

**Step 1: Write the failing test**

Create `tests/gateway/test_ollama_probe.py`:

```python
"""Behavioral tests for Ollama probe — real HTTP against real or absent Ollama."""

import pytest

from corvus.ollama_probe import probe_ollama_models


def test_probe_returns_empty_list_when_unreachable():
    """Probe should return empty list when Ollama is not running."""
    result = probe_ollama_models("http://localhost:99999")
    assert result == []


def test_probe_returns_empty_list_for_invalid_url():
    """Probe should handle invalid URLs gracefully."""
    result = probe_ollama_models("not-a-url")
    assert result == []
```

**Step 2: Run test to verify it fails**

Run: `mise run test -- tests/gateway/test_ollama_probe.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_ollama_probe_results.log`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.ollama_probe'`

**Step 3: Write ollama_probe.py**

Create `corvus/ollama_probe.py`:

```python
"""Ollama model discovery — probe a running Ollama instance for available models."""

import logging

import httpx

logger = logging.getLogger("corvus-gateway.ollama")


def probe_ollama_models(base_url: str, timeout: float = 5.0) -> list[str]:
    """Query Ollama's /api/tags endpoint for available model names.

    Returns an empty list if Ollama is unreachable or returns an error.
    Never raises — errors are logged and swallowed for graceful degradation.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        logger.info("Ollama at %s: found %d models: %s", base_url, len(models), models)
        return models
    except Exception:
        logger.warning("Ollama probe failed at %s", base_url, exc_info=True)
        return []
```

**Step 4: Run test to verify it passes**

Run: `mise run test -- tests/gateway/test_ollama_probe.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_ollama_probe_pass_results.log`
Expected: Both tests PASS

**Step 5: Wire into server.py lifespan**

In `corvus/server.py`, import and call the probe in `_ensure_dirs()` or right after it in `lifespan()`:

Add import at top:
```python
from corvus.ollama_probe import probe_ollama_models
```

Add to lifespan, after `_ensure_dirs()`:

```python
    # Probe Ollama for available models if configured
    ollama_url = os.environ.get("OLLAMA_BASE_URL")
    if ollama_url:
        ollama_models = probe_ollama_models(ollama_url)
        logger.info("Ollama models available: %s", ollama_models)
```

**Step 6: Check httpx is in dependencies**

Run: `grep httpx requirements.txt` or `grep httpx pyproject.toml` — httpx should already be a dependency (FastAPI uses it). If not:

Run: `uv pip install httpx`

**Step 7: Commit**

```bash
git add corvus/ollama_probe.py tests/gateway/test_ollama_probe.py corvus/server.py
git commit -m "feat: add Ollama model probe at server startup"
```

---

### Task 6: Enhance /health endpoint with backend status

**Files:**
- Modify: `corvus/server.py` (health endpoint)

**Step 1: Write the failing test**

Create `tests/gateway/test_health_backends.py`:

```python
"""Test /health endpoint reports backend status."""

import pytest
from fastapi.testclient import TestClient

from corvus.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_includes_backends_key(client):
    """Health response should include a backends dict."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "backends" in data


def test_health_lists_all_backend_names(client):
    """Health should report status for all known backends."""
    resp = client.get("/health")
    data = resp.json()
    backends = data["backends"]
    for name in ("claude", "openai", "ollama", "kimi", "openai_compat"):
        assert name in backends
```

**Step 2: Run test to verify it fails**

Run: `mise run test -- tests/gateway/test_health_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_health_backends_results.log`
Expected: FAIL — current health returns `{"status": "ok", "service": "corvus-gateway"}` with no `backends` key

**Step 3: Update /health endpoint**

In `corvus/server.py`, replace the health endpoint:

```python
@app.get("/health")
async def health():
    """Health check endpoint with backend status."""
    backend_env_map = {
        "claude": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "ollama": "OLLAMA_BASE_URL",
        "kimi": "KIMI_BOT_TOKEN",
        "openai_compat": "OPENAI_COMPAT_BASE_URL",
    }

    backends = {}
    for name, env_var in backend_env_map.items():
        if os.environ.get(env_var):
            backends[name] = {"status": "configured"}
        else:
            backends[name] = {"status": "not_configured"}

    any_llm = any(b["status"] == "configured" for b in backends.values())
    overall = "ok" if any_llm else "degraded"

    return {
        "status": overall,
        "service": "corvus-gateway",
        "backends": backends,
    }
```

**Step 4: Run test to verify it passes**

Run: `mise run test -- tests/gateway/test_health_backends.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_health_backends_pass_results.log`
Expected: Both tests PASS

**Step 5: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_full_results.log`
Expected: All tests PASS (no regressions)

**Step 6: Commit**

```bash
git add corvus/server.py tests/gateway/test_health_backends.py
git commit -m "feat: /health endpoint reports LLM backend status"
```

---

### Task 7: Add graceful chat error when no LLM configured

**Files:**
- Modify: `corvus/server.py` (WebSocket handler)

**Step 1: Identify the chat handler**

The WebSocket chat handler is at `corvus/server.py` in `websocket_chat()`. Find the point where it would dispatch to the LLM and add a guard.

**Step 2: Write the failing test**

Create `tests/gateway/test_chat_no_llm.py`:

```python
"""Test WebSocket chat returns error when no LLM backend is configured."""

import os

import pytest
from fastapi.testclient import TestClient

from corvus.server import app


def test_chat_without_llm_returns_error():
    """WebSocket chat should return no_llm_configured error."""
    # Ensure no LLM env vars are set
    llm_vars = [
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "OLLAMA_BASE_URL", "KIMI_BOT_TOKEN", "OPENAI_COMPAT_BASE_URL",
    ]

    client = TestClient(app)
    with client.websocket_connect(
        "/ws", headers={"X-Remote-User": "patanet7"}
    ) as ws:
        ws.send_json({"type": "chat", "message": "hello"})
        resp = ws.receive_json()
        # If no LLM is configured, response should indicate the error
        if not any(os.environ.get(v) for v in llm_vars):
            assert resp.get("type") == "error"
            assert "no_llm_configured" in resp.get("error", "")
```

**Step 3: Add guard to WebSocket handler**

In the WebSocket handler in `corvus/server.py`, add an early check before LLM dispatch:

```python
def _any_llm_configured() -> bool:
    """Check if any LLM backend has credentials configured."""
    return any(
        os.environ.get(v)
        for v in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "OLLAMA_BASE_URL", "KIMI_BOT_TOKEN", "OPENAI_COMPAT_BASE_URL",
        )
    )
```

In the chat message handling section of `websocket_chat()`, before dispatching to the SDK:

```python
        if not _any_llm_configured():
            await websocket.send_json({
                "type": "error",
                "error": "no_llm_configured",
                "message": "No LLM backend configured. Run 'mise run setup' to add one.",
            })
            continue
```

**Step 4: Run test to verify it passes**

Run: `mise run test -- tests/gateway/test_chat_no_llm.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_chat_no_llm_results.log`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/server.py tests/gateway/test_chat_no_llm.py
git commit -m "feat: graceful error when chat attempted with no LLM backend"
```

---

### Task 8: Update models.yaml with new backend entries

**Files:**
- Modify: `config/models.yaml`

**Step 1: Update models.yaml**

Add `openai` and `openai_compat` backend entries:

```yaml
backends:
  claude:
    type: sdk_native
    # Active when ANTHROPIC_API_KEY is set
  openai:
    type: openai
    # Active when OPENAI_API_KEY is set
  kimi:
    type: proxy
    base_url: "http://localhost:8100"
    env:
      ANTHROPIC_API_KEY: "not-needed"
  ollama:
    type: env_swap
    # base_url from OLLAMA_BASE_URL env var
    env:
      ANTHROPIC_BASE_URL: "http://localhost:11434"
      ANTHROPIC_AUTH_TOKEN: "ollama"
      ANTHROPIC_API_KEY: ""
  openai_compat:
    type: openai
    # base_url from OPENAI_COMPAT_BASE_URL env var
    # api_key from OPENAI_COMPAT_API_KEY env var (optional)
```

**Step 2: Run model router tests**

Run: `mise run test -- tests/gateway/test_model_router.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_model_router_results.log`
Expected: All existing tests PASS

**Step 3: Commit**

```bash
git add config/models.yaml
git commit -m "feat: add openai and openai_compat backend definitions to models.yaml"
```

---

### Task 9: Add mise tasks for frontend dev

**Files:**
- Modify: `mise.toml`

**Step 1: Add frontend tasks**

Add to `mise.toml`:

```toml
[tasks."dev:frontend"]
description = "Start frontend dev server"
run = "cd frontend && pnpm install && pnpm dev"

[tasks."dev:backend"]
description = "Start backend server (alias for serve)"
run = "uv run python -m corvus.server"
```

**Step 2: Verify tasks work**

Run: `mise tasks` to confirm new tasks appear in the list.

**Step 3: Commit**

```bash
git add mise.toml
git commit -m "feat: add mise tasks for frontend dev"
```

---

### Task 10: Final integration test + commit local dev fixes

**Files:**
- Verify: `corvus/config.py` (DATA_DIR fix from earlier)
- Verify: `corvus/server.py` (_ensure_dirs from earlier)
- Verify: `.gitignore` (.data/ entry from earlier)

**Step 1: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_final_full_results.log`
Expected: All tests PASS, including new tests from Tasks 1-7

**Step 2: Test server starts locally**

Run: `timeout 10 mise run serve 2>&1 || true`
Expected: Server starts, logs show backend status, no crashes

**Step 3: Commit any remaining local dev fixes**

```bash
git add corvus/config.py corvus/server.py .gitignore
git commit -m "fix: local dev support — smart DATA_DIR, auto-create dirs, init SQLite"
```

**Step 4: Final commit — all setup wizard changes**

Verify with `git log --oneline` that all commits are clean and well-described.
