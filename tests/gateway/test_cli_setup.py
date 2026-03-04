"""Behavioral tests for the Claw setup CLI — Textual pilot tests."""

import pytest
from textual.widgets import Input

from corvus.cli.setup import ClawSetupApp


class TestWelcomeScreen:
    """Welcome screen renders correctly."""

    @pytest.mark.asyncio
    async def test_welcome_screen_renders_title(self):
        """Welcome screen shows the CLAW SETUP title."""
        async with ClawSetupApp().run_test() as pilot:
            app = pilot.app
            title_widget = app.screen.query_one("#title")
            assert "CLAW SETUP" in str(title_widget.render())


class TestBackendsScreen:
    """Model backends configuration screen."""

    @pytest.mark.asyncio
    async def test_backends_screen_renders(self):
        """Backends screen shows toggle for Claude."""
        async with ClawSetupApp().run_test() as pilot:
            await pilot.click("#next-btn")  # Welcome -> Backends
            screen = pilot.app.screen
            assert screen.query_one("#toggle-claude") is not None

    @pytest.mark.asyncio
    async def test_backends_screen_has_all_toggles(self):
        """Backends screen has toggles for all five backends."""
        async with ClawSetupApp().run_test() as pilot:
            await pilot.click("#next-btn")
            screen = pilot.app.screen
            for backend_id in ("claude", "openai", "ollama", "kimi", "openai-compat"):
                assert screen.query_one(f"#toggle-{backend_id}") is not None


class TestServicesScreen:
    """Service credential configuration screen."""

    @pytest.mark.asyncio
    async def test_services_screen_renders(self):
        """Services screen shows input fields for each service."""
        async with ClawSetupApp().run_test() as pilot:
            # ServicesScreen is already in SCREENS dict, just push it
            pilot.app.push_screen("services")
            await pilot.pause()
            screen = pilot.app.screen
            # Should have HA input fields
            assert screen.query_one("#ha-url") is not None
            assert screen.query_one("#ha-token") is not None


class TestStatusDashboard:
    """Status dashboard shows credential status."""

    @pytest.mark.asyncio
    async def test_status_screen_renders_with_no_store(self):
        """Status screen handles missing credential store gracefully."""
        from corvus.cli.screens.status import StatusScreen

        app = ClawSetupApp()
        async with app.run_test() as pilot:
            pilot.app.install_screen(StatusScreen, name="status")
            pilot.app.push_screen("status")
            await pilot.pause()
            screen = pilot.app.screen
            rendered = str(screen.query_one("#title").render())
            assert "CREDENTIAL STATUS" in rendered


class TestPassphraseScreen:
    """Break-glass passphrase setup screen."""

    @pytest.mark.asyncio
    async def test_passphrase_screen_renders(self):
        """Passphrase screen shows two password inputs."""
        async with ClawSetupApp().run_test() as pilot:
            pilot.app.push_screen("passphrase")
            await pilot.pause()
            screen = pilot.app.screen
            assert screen.query_one("#passphrase-input") is not None
            assert screen.query_one("#confirm-input") is not None

    @pytest.mark.asyncio
    async def test_passphrase_mismatch_disables_finish(self):
        """Finish button stays disabled when passphrases don't match."""
        async with ClawSetupApp().run_test() as pilot:
            pilot.app.push_screen("passphrase")
            await pilot.pause()
            screen = pilot.app.screen
            screen.query_one("#passphrase-input", Input).value = "strong-pass-phrase-123!"
            screen.query_one("#confirm-input", Input).value = "different-phrase"
            await pilot.pause()
            assert screen.query_one("#finish-btn").disabled is True


class TestCompleteScreen:
    """Setup complete summary screen."""

    @pytest.mark.asyncio
    async def test_complete_screen_renders(self):
        """Complete screen shows setup summary."""
        async with ClawSetupApp().run_test() as pilot:
            pilot.app._backends_data = {"claude": {"api-key": "sk-ant-oat01-test"}}
            pilot.app._services_data = {"ha": {"url": "http://ha.local", "token": "t"}}
            pilot.app._passphrase_set = True
            pilot.app.push_screen("complete")
            await pilot.pause()
            screen = pilot.app.screen
            rendered = str(screen.query_one("#title").render())
            assert "SETUP COMPLETE" in rendered
