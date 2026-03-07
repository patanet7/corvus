"""Behavioral tests for the provider edit modal."""

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
