"""Tests for auth profile types."""

from corvus.auth.profiles import (
    ApiKeyCredential,
    AuthProfileStore,
    OAuthCredential,
    TokenCredential,
)


class TestCredentialTypes:
    def test_api_key_credential(self) -> None:
        cred = ApiKeyCredential(provider="anthropic", key="sk-ant-api3...")
        assert cred.type == "api_key"
        assert cred.provider == "anthropic"
        assert cred.key == "sk-ant-api3..."

    def test_token_credential(self) -> None:
        cred = TokenCredential(provider="anthropic", token="sk-ant-oat01-...")
        assert cred.type == "token"
        assert cred.expires is None

    def test_token_credential_with_expiry(self) -> None:
        cred = TokenCredential(provider="anthropic", token="tok", expires=1700000000000)
        assert cred.expires == 1700000000000

    def test_oauth_credential(self) -> None:
        cred = OAuthCredential(
            provider="codex",
            access_token="eyJ...",
            refresh_token="eyJ...",
            expires=1700000000000,
        )
        assert cred.type == "oauth"

    def test_store_empty(self) -> None:
        store = AuthProfileStore()
        assert store.profiles == {}
        assert store.order == {}
        assert store.usage_stats == {}

    def test_store_add_profile(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-ant-..."
        )
        assert "anthropic:default" in store.profiles

    def test_store_serialization_roundtrip(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-ant-..."
        )
        data = store.to_dict()
        restored = AuthProfileStore.from_dict(data)
        assert restored.profiles["anthropic:default"].key == "sk-ant-..."
