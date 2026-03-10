"""Tests for inject() with auth profile support.

Verifies that CredentialStore.inject() resolves credentials from
AuthProfileStore when profiles exist, falling back to flat credentials
when they do not.
"""

from __future__ import annotations

import os

from corvus.auth.profiles import ApiKeyCredential, AuthProfileStore, TokenCredential
from corvus.credential_store import CredentialStore


class TestInjectWithProfiles:
    """Behavioral tests: inject() prefers profiles over flat credentials."""

    def test_inject_uses_profile_over_flat_credential(self) -> None:
        store = CredentialStore.from_env()
        store._data = {
            "anthropic": {"api_key": "sk-flat-key"},
        }
        profiles = AuthProfileStore()
        profiles.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-profile-key"
        )
        store.set_auth_profiles(profiles)

        store.inject()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-profile-key"

    def test_inject_falls_back_to_flat_when_no_profiles(self) -> None:
        store = CredentialStore.from_env()
        store._data = {"anthropic": {"api_key": "sk-flat-key"}}

        store.inject()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-flat-key"

    def test_inject_setup_token_as_oauth(self) -> None:
        """OAuth setup tokens (sk-ant-oat*) route to CLAUDE_CODE_OAUTH_TOKEN."""
        store = CredentialStore.from_env()
        store._data = {}
        profiles = AuthProfileStore()
        profiles.profiles["anthropic:setup"] = TokenCredential(
            provider="anthropic", token="sk-ant-oat01-test-token"
        )
        store.set_auth_profiles(profiles)

        store.inject()
        assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-test-token"
