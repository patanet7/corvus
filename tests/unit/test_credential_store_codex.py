"""Behavioral tests for credential store Codex OAuth integration."""

import os
import time

from corvus.credential_store import CredentialStore


class TestCredentialStoreCodexInject:
    """Tests for inject() handling the codex service."""

    def test_inject_sets_codex_api_key_from_valid_token(self) -> None:
        """inject() must set CODEX_API_KEY when codex tokens are not expired."""
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {
            "codex": {
                "access_token": "valid_access_token",
                "refresh_token": "some_refresh",
                "expires": str(int(time.time()) + 3600),
                "account_id": "acc_123",
            }
        }

        env_before = os.environ.get("CODEX_API_KEY")
        try:
            store.inject()
            assert os.environ["CODEX_API_KEY"] == "valid_access_token"
        finally:
            if env_before is None:
                os.environ.pop("CODEX_API_KEY", None)
            else:
                os.environ["CODEX_API_KEY"] = env_before

    def test_inject_skips_codex_when_not_configured(self) -> None:
        """inject() must not set CODEX_API_KEY when codex is not in store."""
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}

        env_before = os.environ.get("CODEX_API_KEY")
        try:
            os.environ.pop("CODEX_API_KEY", None)
            store.inject()
            assert "CODEX_API_KEY" not in os.environ
        finally:
            if env_before is not None:
                os.environ["CODEX_API_KEY"] = env_before


class TestFromEnvCodex:
    """Tests for from_env() picking up CODEX_API_KEY."""

    def test_from_env_captures_codex_key(self) -> None:
        """from_env() must populate codex service from CODEX_API_KEY env var."""
        env_before = os.environ.get("CODEX_API_KEY")
        try:
            os.environ["CODEX_API_KEY"] = "test_codex_key"
            store = CredentialStore.from_env()
            assert store.get("codex", "access_token") == "test_codex_key"
        finally:
            if env_before is None:
                os.environ.pop("CODEX_API_KEY", None)
            else:
                os.environ["CODEX_API_KEY"] = env_before
