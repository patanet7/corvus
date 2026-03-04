"""Behavioral tests for ModelBackendsScreen — real Textual app pilot."""

import pytest
from textual.app import App

from corvus.cli.screens.backends import ModelBackendsScreen


class BackendsTestApp(App):
    SCREENS = {"backends": ModelBackendsScreen}

    def on_mount(self) -> None:
        self.push_screen("backends")


@pytest.mark.asyncio
async def test_screen_renders_all_backends():
    """All five backend toggles should render."""
    async with BackendsTestApp().run_test() as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        for backend_id in ("claude", "openai", "ollama", "kimi", "openai-compat"):
            toggle = screen.query_one(f"#toggle-{backend_id}")
            assert toggle is not None


@pytest.mark.asyncio
async def test_all_toggles_off_by_default():
    """All backend toggles should be off by default."""
    async with BackendsTestApp().run_test() as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        for backend_id in ("claude", "openai", "ollama", "kimi", "openai-compat"):
            toggle = screen.query_one(f"#toggle-{backend_id}")
            assert toggle.value is False


@pytest.mark.asyncio
async def test_skip_all_button_exists():
    """Skip All button should be present and enabled."""
    async with BackendsTestApp().run_test() as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        skip_btn = screen.query_one("#skip-btn")
        assert skip_btn is not None
        assert skip_btn.disabled is False


@pytest.mark.asyncio
async def test_ollama_default_url():
    """Ollama URL should default to localhost:11434 when toggled on."""
    async with BackendsTestApp().run_test() as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        toggle = screen.query_one("#toggle-ollama")
        toggle.value = True
        await pilot.pause()
        url_input = screen.query_one("#ollama-base-url")
        assert url_input.value == "http://localhost:11434"


@pytest.mark.asyncio
async def test_wizard_has_backends_screen():
    """Setup wizard should register backends screen, not anthropic."""
    from corvus.cli.setup import ClawSetupApp

    app = ClawSetupApp()
    assert "backends" in app.SCREENS
    assert "anthropic" not in app.SCREENS


def test_complete_screen_has_all_backend_labels():
    """CompleteScreen should list all 5 backend labels."""
    from corvus.cli.screens.complete import BACKEND_LABELS

    assert "claude" in BACKEND_LABELS
    assert "openai" in BACKEND_LABELS
    assert "ollama" in BACKEND_LABELS
    assert "kimi" in BACKEND_LABELS
    assert "openai-compat" in BACKEND_LABELS
