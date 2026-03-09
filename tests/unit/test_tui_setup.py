"""Behavioral tests for TUI setup dashboard — credential status display.

Uses a real Rich Console writing to io.StringIO and real os.environ
manipulation. No mocks, no monkeypatch.
"""

import io
import os

from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.theme import TuiTheme


def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    """Build a ChatRenderer backed by a string buffer for assertions."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    return renderer, buf


def _output(buf: io.StringIO) -> str:
    """Return everything written so far and reset."""
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


# ---------------------------------------------------------------------------
# Environment variable helpers — real os.environ manipulation
# ---------------------------------------------------------------------------

# Keys that our tests will set/unset. We save and restore originals.
_TEST_ENV_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_HOST",
    "GMAIL_CREDENTIALS",
    "GOOGLE_CLIENT_ID",
    "HA_TOKEN",
    "HA_URL",
    "PAPERLESS_TOKEN",
    "PAPERLESS_URL",
    "FIREFLY_TOKEN",
    "FIREFLY_URL",
]


def _save_env() -> dict[str, str | None]:
    """Snapshot current values for test env keys."""
    return {k: os.environ.get(k) for k in _TEST_ENV_KEYS}


def _restore_env(snapshot: dict[str, str | None]) -> None:
    """Restore env vars from a snapshot."""
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _clear_all_test_env() -> None:
    """Remove all test env keys."""
    for key in _TEST_ENV_KEYS:
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# render_setup_dashboard tests
# ---------------------------------------------------------------------------

class TestRenderSetupDashboard:
    """Tests for ChatRenderer.render_setup_dashboard()."""

    def test_shows_table_with_provider_names(self) -> None:
        renderer, buf = _make_renderer()
        providers = [
            {"name": "Anthropic", "configured": True, "detail": "ANTHROPIC_API_KEY set"},
            {"name": "OpenAI", "configured": False, "detail": "OPENAI_API_KEY missing"},
        ]
        renderer.render_setup_dashboard(providers)
        output = _output(buf)
        assert "Anthropic" in output
        assert "OpenAI" in output

    def test_shows_configured_status_with_green_marker(self) -> None:
        renderer, buf = _make_renderer()
        providers = [
            {"name": "Anthropic", "configured": True, "detail": "ANTHROPIC_API_KEY set"},
        ]
        renderer.render_setup_dashboard(providers)
        output = _output(buf)
        # Green filled circle for configured
        assert "\u25cf" in output  # ● character
        assert "Configured" in output

    def test_shows_not_configured_status_with_red_marker(self) -> None:
        renderer, buf = _make_renderer()
        providers = [
            {"name": "OpenAI", "configured": False, "detail": "OPENAI_API_KEY missing"},
        ]
        renderer.render_setup_dashboard(providers)
        output = _output(buf)
        # Red open circle for not configured
        assert "\u25cb" in output  # ○ character
        assert "Not Configured" in output

    def test_shows_mixed_status(self) -> None:
        renderer, buf = _make_renderer()
        providers = [
            {"name": "Anthropic", "configured": True, "detail": "ANTHROPIC_API_KEY set"},
            {"name": "OpenAI", "configured": False, "detail": "OPENAI_API_KEY missing"},
            {"name": "Ollama", "configured": True, "detail": "localhost:11434"},
        ]
        renderer.render_setup_dashboard(providers)
        output = _output(buf)
        assert "Anthropic" in output
        assert "OpenAI" in output
        assert "Ollama" in output
        # Both markers present
        assert "\u25cf" in output  # ● configured
        assert "\u25cb" in output  # ○ not configured

    def test_shows_detail_column(self) -> None:
        renderer, buf = _make_renderer()
        providers = [
            {"name": "Ollama", "configured": True, "detail": "localhost:11434"},
        ]
        renderer.render_setup_dashboard(providers)
        output = _output(buf)
        assert "localhost:11434" in output

    def test_empty_providers_shows_message(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_setup_dashboard([])
        output = _output(buf)
        assert "No providers configured" in output

    def test_table_has_header_columns(self) -> None:
        renderer, buf = _make_renderer()
        providers = [
            {"name": "Anthropic", "configured": True, "detail": "set"},
        ]
        renderer.render_setup_dashboard(providers)
        output = _output(buf)
        assert "Provider" in output
        assert "Status" in output
        assert "Details" in output


# ---------------------------------------------------------------------------
# get_credential_status tests — real os.environ
# ---------------------------------------------------------------------------

class TestGetCredentialStatus:
    """Tests for _get_credential_status() reading real environment variables."""

    def setup_method(self) -> None:
        self._snapshot = _save_env()
        _clear_all_test_env()

    def teardown_method(self) -> None:
        _restore_env(self._snapshot)

    def test_all_unconfigured_when_env_empty(self) -> None:
        app = TuiApp()
        status = app._get_credential_status()
        assert isinstance(status, list)
        assert len(status) > 0
        for provider in status:
            # Ollama defaults to configured (localhost)
            if provider["name"] == "Ollama":
                continue
            assert provider["configured"] is False, (
                f"{provider['name']} should be not configured"
            )

    def test_anthropic_configured_when_key_set(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-key-123"
        app = TuiApp()
        status = app._get_credential_status()
        anthropic = [p for p in status if p["name"] == "Anthropic"][0]
        assert anthropic["configured"] is True

    def test_openai_configured_when_key_set(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-openai-test"
        app = TuiApp()
        status = app._get_credential_status()
        openai = [p for p in status if p["name"] == "OpenAI"][0]
        assert openai["configured"] is True

    def test_ollama_defaults_to_configured(self) -> None:
        """Ollama is considered configured even without OLLAMA_HOST (defaults to localhost)."""
        app = TuiApp()
        status = app._get_credential_status()
        ollama = [p for p in status if p["name"] == "Ollama"][0]
        assert ollama["configured"] is True
        assert "localhost" in ollama["detail"]

    def test_ollama_custom_host(self) -> None:
        os.environ["OLLAMA_HOST"] = "http://gpu-server:11434"
        app = TuiApp()
        status = app._get_credential_status()
        ollama = [p for p in status if p["name"] == "Ollama"][0]
        assert ollama["configured"] is True
        assert "gpu-server" in ollama["detail"]

    def test_gmail_configured_via_credentials(self) -> None:
        os.environ["GMAIL_CREDENTIALS"] = "/path/to/creds.json"
        app = TuiApp()
        status = app._get_credential_status()
        gmail = [p for p in status if p["name"] == "Gmail"][0]
        assert gmail["configured"] is True

    def test_gmail_configured_via_client_id(self) -> None:
        os.environ["GOOGLE_CLIENT_ID"] = "123-abc.apps.googleusercontent.com"
        app = TuiApp()
        status = app._get_credential_status()
        gmail = [p for p in status if p["name"] == "Gmail"][0]
        assert gmail["configured"] is True

    def test_home_assistant_configured_via_token(self) -> None:
        os.environ["HA_TOKEN"] = "eyJ0b2tlbiI6InRlc3QifQ"
        app = TuiApp()
        status = app._get_credential_status()
        ha = [p for p in status if p["name"] == "Home Assistant"][0]
        assert ha["configured"] is True

    def test_home_assistant_configured_via_url(self) -> None:
        os.environ["HA_URL"] = "http://homeassistant.local:8123"
        app = TuiApp()
        status = app._get_credential_status()
        ha = [p for p in status if p["name"] == "Home Assistant"][0]
        assert ha["configured"] is True

    def test_paperless_configured_via_token(self) -> None:
        os.environ["PAPERLESS_TOKEN"] = "abc123token"
        app = TuiApp()
        status = app._get_credential_status()
        paperless = [p for p in status if p["name"] == "Paperless"][0]
        assert paperless["configured"] is True

    def test_firefly_configured_via_token(self) -> None:
        os.environ["FIREFLY_TOKEN"] = "firefly-pat-123"
        app = TuiApp()
        status = app._get_credential_status()
        firefly = [p for p in status if p["name"] == "Firefly"][0]
        assert firefly["configured"] is True

    def test_returns_all_seven_providers(self) -> None:
        app = TuiApp()
        status = app._get_credential_status()
        names = {p["name"] for p in status}
        expected = {"Anthropic", "OpenAI", "Ollama", "Gmail", "Home Assistant", "Paperless", "Firefly"}
        assert names == expected

    def test_each_provider_has_required_keys(self) -> None:
        app = TuiApp()
        status = app._get_credential_status()
        for provider in status:
            assert "name" in provider
            assert "configured" in provider
            assert "detail" in provider
            assert isinstance(provider["name"], str)
            assert isinstance(provider["configured"], bool)
            assert isinstance(provider["detail"], str)


# ---------------------------------------------------------------------------
# _handle_setup_command integration tests
# ---------------------------------------------------------------------------

class TestHandleSetupCommand:
    """Tests for TuiApp._handle_setup_command() wiring."""

    def setup_method(self) -> None:
        self._snapshot = _save_env()
        _clear_all_test_env()

    def teardown_method(self) -> None:
        _restore_env(self._snapshot)

    def test_setup_no_args_renders_dashboard(self) -> None:
        app = TuiApp()
        # Replace console with captured one
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(console=console, theme=app.theme)

        app._handle_setup_command(None)
        output = _output(buf)
        assert "Provider" in output
        assert "Anthropic" in output

    def test_setup_status_renders_dashboard(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(console=console, theme=app.theme)

        app._handle_setup_command("status")
        output = _output(buf)
        assert "Provider" in output
        assert "Anthropic" in output

    def test_setup_with_configured_provider_shows_configured(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-abc"
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.renderer = ChatRenderer(console=console, theme=app.theme)

        app._handle_setup_command(None)
        output = _output(buf)
        assert "configured" in output.lower()
        assert "Anthropic" in output
