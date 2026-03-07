"""Behavioral tests for corvus.auth.openai_oauth — PKCE helpers."""

import base64
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from corvus.auth.openai_oauth import (
    OAuthTokens,
    build_authorize_url,
    decode_jwt_account_id,
    exchange_code_for_tokens,
    generate_pkce,
    refresh_access_token,
)


def _make_fake_jwt(payload: dict) -> str:
    """Build a fake JWT (header.payload.signature) for testing."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


class TestGeneratePkce:
    """Tests for PKCE code_verifier and code_challenge generation."""

    def test_verifier_length(self) -> None:
        """Verifier must be 43-128 chars per RFC 7636."""
        pkce = generate_pkce()
        assert 43 <= len(pkce.verifier) <= 128

    def test_verifier_is_url_safe(self) -> None:
        """Verifier must be URL-safe base64 characters only."""
        pkce = generate_pkce()
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert all(c in allowed for c in pkce.verifier)

    def test_challenge_matches_verifier(self) -> None:
        """Challenge must be SHA256(verifier) base64url-encoded."""
        pkce = generate_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(pkce.verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert pkce.challenge == expected

    def test_state_is_nonempty(self) -> None:
        """State must be a nonempty random string."""
        pkce = generate_pkce()
        assert len(pkce.state) >= 16


class TestBuildAuthorizeUrl:
    """Tests for OAuth authorize URL construction."""

    def test_url_contains_required_params(self) -> None:
        """URL must contain client_id, redirect_uri, code_challenge, state."""
        pkce = generate_pkce()
        url = build_authorize_url(pkce)
        assert "auth.openai.com" in url
        assert "code_challenge=" in url
        assert "state=" + pkce.state in url
        assert "code_challenge_method=S256" in url
        assert "redirect_uri=" in url


class TestDecodeJwtAccountId:
    """Tests for JWT account_id extraction."""

    def test_extracts_account_id(self) -> None:
        """Must extract chatgpt_account_id from OpenAI JWT claims."""
        token = _make_fake_jwt({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc_abc123"},
            "sub": "user123",
        })
        assert decode_jwt_account_id(token) == "acc_abc123"

    def test_returns_empty_on_missing_claim(self) -> None:
        """Must return empty string if claim is missing."""
        token = _make_fake_jwt({"sub": "user123"})
        assert decode_jwt_account_id(token) == ""


class TestExchangeCodeForTokens:
    """Tests for OAuth token exchange against a fake token endpoint."""

    def test_exchanges_code_successfully(self) -> None:
        """Must POST to token endpoint and return OAuthTokens."""
        fake_access = _make_fake_jwt({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc_test"},
        })
        response_body = json.dumps({
            "access_token": fake_access,
            "refresh_token": "refresh_xyz",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()

        try:
            result = exchange_code_for_tokens(
                code="test_code",
                verifier="test_verifier",
                token_url=f"http://127.0.0.1:{port}/oauth/token",
            )
        finally:
            server.server_close()
            thread.join(timeout=2)

        assert isinstance(result, OAuthTokens)
        assert result.access_token == fake_access
        assert result.refresh_token == "refresh_xyz"
        assert result.account_id == "acc_test"
        assert result.expires > int(time.time())


class TestRefreshAccessToken:
    """Tests for OAuth token refresh."""

    def test_refresh_returns_new_tokens(self) -> None:
        """Must POST to token endpoint with refresh_token grant and return new tokens."""
        new_access = _make_fake_jwt({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc_refreshed"},
        })
        response_body = json.dumps({
            "access_token": new_access,
            "refresh_token": "new_refresh_xyz",
            "expires_in": 7200,
        }).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()

        try:
            result = refresh_access_token(
                refresh_token="old_refresh",
                token_url=f"http://127.0.0.1:{port}/oauth/token",
            )
        finally:
            server.server_close()
            thread.join(timeout=2)

        assert result.access_token == new_access
        assert result.refresh_token == "new_refresh_xyz"
        assert result.account_id == "acc_refreshed"
        assert result.expires > int(time.time())
