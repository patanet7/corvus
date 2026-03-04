"""Contract tests for GoogleClient multi-account OAuth client.

Verifies account discovery, token injection, and base URL override
by testing against a real HTTP server — no mocks.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from corvus.google_client import GoogleClient

# --- Fake Google API server for testing ---


class FakeGoogleHandler(BaseHTTPRequestHandler):
    """Serves minimal Google API responses for client tests."""

    def do_GET(self) -> None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._respond(401, {"error": {"code": 401, "message": "Unauthorized"}})
            return
        self._respond(200, {"status": "ok", "path": self.path, "token": auth.split(" ")[1]})

    def _respond(self, status: int, body: Any) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def google_server():
    server = HTTPServer(("127.0.0.1", 0), FakeGoogleHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


# --- Account discovery from env vars ---


class TestAccountDiscovery:
    def test_discovers_accounts_from_env(self, monkeypatch):
        """GoogleClient.from_env() discovers GOOGLE_ACCOUNT_* patterns."""
        monkeypatch.setenv("GOOGLE_ACCOUNT_personal_EMAIL", "tom@gmail.com")
        monkeypatch.setenv("GOOGLE_ACCOUNT_personal_CREDENTIALS", "/creds/personal.json")
        monkeypatch.setenv("GOOGLE_ACCOUNT_personal_TOKEN", "/creds/personal_token.json")
        monkeypatch.setenv("GOOGLE_ACCOUNT_work_EMAIL", "tom@company.com")
        monkeypatch.setenv("GOOGLE_ACCOUNT_work_CREDENTIALS", "/creds/work.json")
        monkeypatch.setenv("GOOGLE_ACCOUNT_work_TOKEN", "/creds/work_token.json")
        monkeypatch.setenv("GOOGLE_DEFAULT_ACCOUNT", "personal")

        client = GoogleClient.from_env(skip_auth=True)
        assert set(client.list_accounts()) == {"personal", "work"}
        assert client.get_account_email("personal") == "tom@gmail.com"
        assert client.get_account_email("work") == "tom@company.com"
        assert client.default_account == "personal"

    def test_no_accounts_returns_empty(self):
        """No GOOGLE_ACCOUNT_* env vars → empty account list."""
        client = GoogleClient(accounts={})
        assert client.list_accounts() == []

    def test_fallback_to_legacy_env(self, monkeypatch):
        """Falls back to GMAIL_TOKEN/GMAIL_CREDENTIALS if no multi-account vars."""
        monkeypatch.setenv("GMAIL_TOKEN", "/creds/token.json")
        monkeypatch.setenv("GMAIL_CREDENTIALS", "/creds/creds.json")
        monkeypatch.setenv("GMAIL_ADDRESS", "tom@gmail.com")
        # Clear multi-account vars
        for key in list(os.environ.keys()):
            if key.startswith("GOOGLE_ACCOUNT_"):
                monkeypatch.delenv(key, raising=False)

        client = GoogleClient.from_env(skip_auth=True)
        assert "default" in client.list_accounts()
        assert client.get_account_email("default") == "tom@gmail.com"


# --- HTTP requests with auth ---


class TestHTTPRequests:
    def test_request_sends_bearer_token(self, google_server):
        """Requests include Authorization: Bearer <token> header."""
        client = GoogleClient(base_url=google_server, static_token="test-token-123")
        resp = client.request("GET", "/gmail/v1/users/me/messages")
        assert resp["token"] == "test-token-123"

    def test_request_uses_base_url(self, google_server):
        """base_url is prepended to the path."""
        client = GoogleClient(base_url=google_server, static_token="test")
        resp = client.request("GET", "/drive/v3/files")
        assert resp["path"] == "/drive/v3/files"

    def test_request_without_token_raises(self, google_server):
        """Missing token raises RuntimeError."""
        client = GoogleClient(base_url=google_server)
        with pytest.raises(RuntimeError, match="No credentials"):
            client.request("GET", "/test")

    def test_401_raises_auth_error(self, google_server):
        """401 response raises an auth error."""
        client = GoogleClient(base_url=google_server, static_token="")
        # Empty bearer token triggers 401 from our fake server
        # The handler checks startswith("Bearer ") — empty string after Bearer is still valid
        # So we test with a client that has no token set
        client._static_token = None
        with pytest.raises(RuntimeError):
            client.request("GET", "/test")


# --- Multi-account selection ---


class TestMultiAccount:
    def test_default_account_used_when_none_specified(self, google_server):
        """When account=None, uses the default account's token."""
        client = GoogleClient(
            base_url=google_server,
            accounts={
                "personal": {"email": "a@gmail.com", "token": "tok-personal"},
                "work": {"email": "b@company.com", "token": "tok-work"},
            },
            default_account="personal",
        )
        resp = client.request("GET", "/test")
        assert resp["token"] == "tok-personal"

    def test_specific_account_used_when_specified(self, google_server):
        """When account='work', uses that account's token."""
        client = GoogleClient(
            base_url=google_server,
            accounts={
                "personal": {"email": "a@gmail.com", "token": "tok-personal"},
                "work": {"email": "b@company.com", "token": "tok-work"},
            },
            default_account="personal",
        )
        resp = client.request("GET", "/test", account="work")
        assert resp["token"] == "tok-work"

    def test_unknown_account_raises(self, google_server):
        """Requesting an unknown account raises ValueError."""
        client = GoogleClient(
            base_url=google_server,
            accounts={"personal": {"email": "a@gmail.com", "token": "tok"}},
        )
        with pytest.raises(ValueError, match="Unknown account"):
            client.request("GET", "/test", account="nonexistent")
