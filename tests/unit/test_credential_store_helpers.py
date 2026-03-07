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

    def test_set_bulk_writes_multiple_keys(self) -> None:
        """set_bulk should write all keys then encrypt once."""
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
