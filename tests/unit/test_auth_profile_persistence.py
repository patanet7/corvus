"""Tests for auth profile persistence in credential store."""

from corvus.auth.profiles import ApiKeyCredential, AuthProfileStore
from corvus.credential_store import CredentialStore


class TestAuthProfilePersistence:
    def test_empty_store_returns_empty_profiles(self) -> None:
        store = CredentialStore.from_env()
        profiles = store.get_auth_profiles()
        assert profiles.profiles == {}

    def test_set_and_get_auth_profiles(self) -> None:
        store = CredentialStore.from_env()
        store._data = {}

        profiles = AuthProfileStore()
        profiles.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-ant-test"
        )
        store.set_auth_profiles(profiles)

        restored = store.get_auth_profiles()
        assert "anthropic:default" in restored.profiles
        assert restored.profiles["anthropic:default"].key == "sk-ant-test"

    def test_auth_profiles_stored_under_reserved_key(self) -> None:
        store = CredentialStore.from_env()
        store._data = {}

        profiles = AuthProfileStore()
        profiles.profiles["openai:default"] = ApiKeyCredential(
            provider="openai", key="sk-test"
        )
        store.set_auth_profiles(profiles)

        assert "_auth_profiles" in store._data
