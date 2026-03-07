"""Behavioral tests for the setup dashboard screen."""

import pytest
from textual.app import App

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

    @pytest.mark.asyncio
    async def test_dashboard_mounts_with_all_providers(self) -> None:
        async with DashboardTestApp().run_test() as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            rows = screen.query(ProviderRow)
            provider_ids = [r.provider_id for r in rows]
            assert "claude" in provider_ids
            assert "openai" in provider_ids
            assert "codex" in provider_ids
            assert "ollama" in provider_ids
            assert "ha" in provider_ids
            assert "paperless" in provider_ids

    @pytest.mark.asyncio
    async def test_dashboard_shows_section_headers(self) -> None:
        async with DashboardTestApp().run_test() as pilot:
            await pilot.pause()
            section_headers = pilot.app.screen.query(".section-header")
            assert len(list(section_headers)) >= 2
