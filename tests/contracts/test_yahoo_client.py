"""Tests for YahooClient multi-account discovery.

IMAP connection tests are skipped unless a real Yahoo server is available.
Account discovery from env vars is tested without network access.
"""

import os

import pytest

from corvus.yahoo_client import YahooClient


class TestAccountDiscovery:
    def test_discovers_accounts_from_env(self, monkeypatch):
        monkeypatch.setenv("YAHOO_ACCOUNT_main_EMAIL", "tom@yahoo.com")
        monkeypatch.setenv("YAHOO_ACCOUNT_main_APP_PASSWORD", "xxxx-xxxx-xxxx-xxxx")
        monkeypatch.setenv("YAHOO_ACCOUNT_alt_EMAIL", "alt@yahoo.com")
        monkeypatch.setenv("YAHOO_ACCOUNT_alt_APP_PASSWORD", "yyyy-yyyy-yyyy-yyyy")

        client = YahooClient.from_env()
        assert set(client.list_accounts()) == {"main", "alt"}
        assert client.get_account_email("main") == "tom@yahoo.com"

    def test_no_accounts_returns_empty(self):
        client = YahooClient(accounts={})
        assert client.list_accounts() == []

    def test_fallback_to_legacy_env(self, monkeypatch):
        for key in list(os.environ.keys()):
            if key.startswith("YAHOO_ACCOUNT_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("YAHOO_EMAIL", "tom@yahoo.com")
        monkeypatch.setenv("YAHOO_APP_PASSWORD", "xxxx")

        client = YahooClient.from_env()
        assert "default" in client.list_accounts()

    def test_unknown_account_raises(self):
        client = YahooClient(accounts={"main": {"email": "a@yahoo.com", "app_password": "x"}})
        with pytest.raises(ValueError, match="Unknown account"):
            client.get_connection_params("nonexistent")

    def test_get_connection_params(self):
        client = YahooClient(accounts={"main": {"email": "a@yahoo.com", "app_password": "pass123"}})
        params = client.get_connection_params("main")
        assert params["host"] == "imap.mail.yahoo.com"
        assert params["email"] == "a@yahoo.com"
        assert params["password"] == "pass123"
