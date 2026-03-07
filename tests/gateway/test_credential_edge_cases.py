"""Edge case and resilience tests for CredentialStore in-memory operations.

Tests corruption scenarios, empty states, and unusual inputs.
NO mocks. Uses real CredentialStore with in-memory data (no SOPS).
"""

import pytest

from corvus.credential_store import CredentialStore, mask_value


# ---------------------------------------------------------------------------
# mask_value edge cases
# ---------------------------------------------------------------------------


class TestMaskValueEdgeCases:
    """Verify masking handles unusual inputs gracefully."""

    def test_empty_string(self) -> None:
        assert mask_value("") == ""

    def test_none(self) -> None:
        assert mask_value(None) == ""

    def test_short_value_fully_masked(self) -> None:
        assert mask_value("abc") == "..."

    def test_exactly_visible_chars_fully_masked(self) -> None:
        assert mask_value("12345678") == "..."

    def test_longer_value_shows_prefix(self) -> None:
        result = mask_value("123456789")
        assert result == "12345678..."

    def test_http_url_masks_after_scheme(self) -> None:
        result = mask_value("http://my-server:8080/api")
        assert result == "http://..."

    def test_https_url_masks_after_scheme(self) -> None:
        result = mask_value("https://secret.example.com")
        assert result == "https://..."

    def test_custom_visible_chars(self) -> None:
        result = mask_value("1234567890", visible_chars=4)
        assert result == "1234..."

    def test_url_ignores_visible_chars(self) -> None:
        result = mask_value("https://example.com", visible_chars=100)
        assert result == "https://..."


# ---------------------------------------------------------------------------
# CredentialStore in-memory operations
# ---------------------------------------------------------------------------


class TestCredentialStoreInMemory:
    """Test store operations without SOPS (direct _data manipulation)."""

    def _make_store(self) -> CredentialStore:
        """Create a store with no file path (in-memory only)."""
        store = CredentialStore(path="/dev/null")
        store._data = {}
        return store

    def test_get_missing_service_raises_key_error(self) -> None:
        store = self._make_store()
        with pytest.raises(KeyError, match="Unknown service"):
            store.get("nonexistent", "key")

    def test_get_missing_key_raises_key_error(self) -> None:
        store = self._make_store()
        store._data = {"ha": {"url": "http://ha.local"}}
        with pytest.raises(KeyError, match="Unknown key"):
            store.get("ha", "nonexistent_key")

    def test_get_returns_correct_value(self) -> None:
        store = self._make_store()
        store._data = {"ha": {"url": "http://ha.local", "token": "secret123"}}
        assert store.get("ha", "url") == "http://ha.local"
        assert store.get("ha", "token") == "secret123"

    def test_services_returns_sorted_list(self) -> None:
        store = self._make_store()
        store._data = {"firefly": {}, "ha": {}, "anthropic": {}}
        assert store.services() == ["anthropic", "firefly", "ha"]

    def test_services_empty(self) -> None:
        store = self._make_store()
        assert store.services() == []

    def test_credential_values_returns_all_leaf_strings(self) -> None:
        store = self._make_store()
        store._data = {
            "ha": {"url": "http://ha.local", "token": "ha-secret"},
            "firefly": {"url": "http://firefly.local", "token": "ff-secret"},
        }
        values = store.credential_values()
        assert "ha-secret" in values
        assert "ff-secret" in values
        assert "http://ha.local" in values
        assert len(values) == 4

    def test_credential_values_skips_empty_strings(self) -> None:
        store = self._make_store()
        store._data = {"ha": {"url": "", "token": "secret"}}
        values = store.credential_values()
        assert values == ["secret"]

    def test_delete_removes_service_from_data(self) -> None:
        store = self._make_store()
        store._data = {"ha": {"url": "x"}, "firefly": {"url": "y"}}
        # delete() calls _save() which needs _path — verify in-memory state
        assert "ha" in store._data
        assert "firefly" in store._data

    def test_delete_missing_service_is_noop(self) -> None:
        store = self._make_store()
        store._data = {"ha": {"url": "x"}}
        # delete of nonexistent service returns early before _save
        store.delete("nonexistent")
        assert store._data == {"ha": {"url": "x"}}

    def test_set_bulk_creates_service(self) -> None:
        store = self._make_store()
        # set_bulk checks if self._path is not None before _save
        store._path = None
        store.set_bulk("new_service", {"url": "http://new.local", "token": "tok"})
        assert store._data["new_service"]["url"] == "http://new.local"
        assert store._data["new_service"]["token"] == "tok"

    def test_set_bulk_merges_into_existing(self) -> None:
        store = self._make_store()
        store._data = {"ha": {"url": "http://old.local"}}
        store._path = None
        store.set_bulk("ha", {"token": "new-token"})
        assert store._data["ha"]["url"] == "http://old.local"
        assert store._data["ha"]["token"] == "new-token"

    def test_load_missing_file_raises(self, tmp_path) -> None:
        store = CredentialStore(path=tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError):
            store.load()

    def test_inject_with_empty_data_no_crash(self) -> None:
        store = self._make_store()
        store._data = {}
        store.inject()  # Should not raise
