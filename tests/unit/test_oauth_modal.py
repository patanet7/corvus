"""Behavioral tests for OAuth provider modal."""

from corvus.cli.screens.oauth_modal import OAuthModal


class TestOAuthModal:
    def test_modal_has_provider_id(self) -> None:
        modal = OAuthModal(provider_id="codex", label="Codex (ChatGPT)")
        assert modal.provider_id == "codex"

    def test_modal_has_label(self) -> None:
        modal = OAuthModal(provider_id="codex", label="Codex (ChatGPT)")
        assert modal.label == "Codex (ChatGPT)"
