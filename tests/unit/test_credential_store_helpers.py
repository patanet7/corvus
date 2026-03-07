"""Tests for CredentialStore mask_value and set_bulk helpers."""

from corvus.credential_store import CredentialStore, mask_value


class TestMaskValue:
    """Tests for the mask_value utility function."""

    def test_masks_api_key(self) -> None:
        assert mask_value("sk-ant-api3abc123xyz") == "sk-ant-a..."

    def test_masks_short_value(self) -> None:
        """Values shorter than 8 chars get fully masked."""
        assert mask_value("short") == "..."

    def test_masks_exactly_8_chars(self) -> None:
        """Value with exactly visible_chars length is fully masked."""
        assert mask_value("12345678") == "..."

    def test_masks_https_url(self) -> None:
        assert mask_value("https://ha.local:8123/api") == "https://..."

    def test_masks_http_url(self) -> None:
        assert mask_value("http://internal-server/api") == "http://..."

    def test_empty_string(self) -> None:
        assert mask_value("") == ""

    def test_none_returns_empty(self) -> None:
        assert mask_value(None) == ""


class TestSetBulk:
    """Tests for set_bulk (batch write without per-key SOPS encrypt)."""

    def test_set_bulk_writes_multiple_keys(self) -> None:
        """set_bulk should write all keys then encrypt once."""
        store = CredentialStore.from_env()

        store.set_bulk("codex", {
            "access_token": "tok_abc",
            "refresh_token": "tok_ref",
            "expires": "999999",
        })

        assert store.get("codex", "access_token") == "tok_abc"
        assert store.get("codex", "refresh_token") == "tok_ref"
        assert store.get("codex", "expires") == "999999"

    def test_set_bulk_merges_with_existing(self) -> None:
        store = CredentialStore.from_env()
        store.set_bulk("codex", {"account_id": "acc_123"})

        store.set_bulk("codex", {"access_token": "new_tok"})

        assert store.get("codex", "account_id") == "acc_123"
        assert store.get("codex", "access_token") == "new_tok"
