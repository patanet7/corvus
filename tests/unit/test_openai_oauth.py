"""Behavioral tests for corvus.auth.openai_oauth — PKCE helpers."""

import base64
import hashlib

from corvus.auth.openai_oauth import build_authorize_url, generate_pkce


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
