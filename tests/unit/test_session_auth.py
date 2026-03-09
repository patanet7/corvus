"""Behavioral tests for SessionAuthManager.

Tests exercise real token creation, signing, validation, and the
authenticate() entry point with various auth scenarios.

NO MOCKS — all tests use real SessionAuthManager instances with
real cryptographic operations.
"""

from __future__ import annotations

import base64
import json
import os
import time

import pytest

from corvus.security.session_auth import AuthResult, SessionAuthManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SECRET = os.urandom(64)
ALLOWED = ["alice", "bob"]


TRUSTED_PROXY = "10.0.0.1"


def _make_manager(
    secret: bytes = SECRET,
    allowed_users: list[str] | None = None,
    trusted_proxy_ips: set[str] | None = None,
) -> SessionAuthManager:
    return SessionAuthManager(
        secret=secret,
        allowed_users=allowed_users or ALLOWED,
        trusted_proxy_ips=trusted_proxy_ips,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_rejects_short_secret(self):
        with pytest.raises(ValueError, match="at least 32 bytes"):
            SessionAuthManager(secret=b"tooshort", allowed_users=["alice"])

    def test_accepts_valid_secret(self):
        mgr = _make_manager()
        assert mgr is not None


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


class TestCreateToken:
    def test_creates_token_for_allowed_user(self):
        mgr = _make_manager()
        token = mgr.create_session_token("alice")
        assert isinstance(token, str)
        assert "." in token

    def test_rejects_unknown_user(self):
        mgr = _make_manager()
        with pytest.raises(ValueError, match="not in allowed users"):
            mgr.create_session_token("mallory")

    def test_rejects_non_positive_ttl(self):
        mgr = _make_manager()
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            mgr.create_session_token("alice", ttl_seconds=0)

    def test_token_payload_contains_user_and_exp(self):
        mgr = _make_manager()
        token = mgr.create_session_token("alice", ttl_seconds=3600)
        payload_b64 = token.split(".")[0]
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        assert payload["user"] == "alice"
        assert payload["exp"] > time.time()
        assert payload["exp"] <= time.time() + 3600 + 1


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


class TestValidateToken:
    def test_valid_token_accepted(self):
        mgr = _make_manager()
        token = mgr.create_session_token("alice")
        result = mgr.validate_session_token(token)
        assert result.authenticated is True
        assert result.user == "alice"

    def test_tampered_signature_rejected(self):
        mgr = _make_manager()
        token = mgr.create_session_token("alice")
        payload_b64, _sig = token.split(".")
        tampered = f"{payload_b64}.{'a' * 64}"
        result = mgr.validate_session_token(tampered)
        assert result.authenticated is False
        assert result.reason == "Invalid signature"

    def test_tampered_payload_rejected(self):
        mgr = _make_manager()
        token = mgr.create_session_token("alice")
        _payload_b64, sig = token.split(".")
        # Forge a different payload but keep original sig
        fake_payload = base64.urlsafe_b64encode(
            json.dumps({"user": "mallory", "exp": int(time.time()) + 9999}).encode()
        ).decode()
        forged = f"{fake_payload}.{sig}"
        result = mgr.validate_session_token(forged)
        assert result.authenticated is False
        assert result.reason == "Invalid signature"

    def test_expired_token_rejected(self):
        mgr = _make_manager()
        # Manually create an already-expired token
        payload = {"user": "alice", "exp": int(time.time()) - 10}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        import hashlib
        import hmac as hmac_mod

        sig = hmac_mod.new(SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()
        expired_token = f"{payload_b64}.{sig}"

        result = mgr.validate_session_token(expired_token)
        assert result.authenticated is False
        assert result.reason == "Token expired"

    def test_invalid_format_rejected(self):
        mgr = _make_manager()
        result = mgr.validate_session_token("no-dot-here")
        assert result.authenticated is False
        assert result.reason == "Invalid token format"

        result = mgr.validate_session_token("a.b.c")
        assert result.authenticated is False
        assert result.reason == "Invalid token format"

    def test_user_not_in_allowed_rejected(self):
        """Token signed correctly but user was removed from allowed list."""
        secret = os.urandom(64)
        mgr_wide = SessionAuthManager(
            secret=secret, allowed_users=["alice", "bob"]
        )
        token = mgr_wide.create_session_token("bob")

        # Validate with a manager that no longer allows bob
        mgr_narrow = SessionAuthManager(secret=secret, allowed_users=["alice"])
        result = mgr_narrow.validate_session_token(token)
        assert result.authenticated is False
        assert result.reason == "User not allowed"

    def test_different_secret_rejected(self):
        mgr1 = _make_manager(secret=os.urandom(64))
        mgr2 = _make_manager(secret=os.urandom(64))
        token = mgr1.create_session_token("alice")
        result = mgr2.validate_session_token(token)
        assert result.authenticated is False
        assert result.reason == "Invalid signature"


# ---------------------------------------------------------------------------
# authenticate() entry point
# ---------------------------------------------------------------------------


class TestAuthenticate:
    def test_header_auth_from_trusted_proxy_accepted(self):
        """Proxy headers accepted when client_host is in trusted_proxy_ips."""
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        result = mgr.authenticate(
            client_host=TRUSTED_PROXY,
            token=None,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is True
        assert result.user == "alice"

    def test_remote_user_header_from_trusted_proxy_accepted(self):
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        result = mgr.authenticate(
            client_host=TRUSTED_PROXY,
            token=None,
            headers={"remote-user": "bob"},
        )
        assert result.authenticated is True
        assert result.user == "bob"

    def test_header_from_untrusted_ip_ignored(self):
        """C1: Proxy headers from an IP NOT in trusted_proxy_ips are ignored."""
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        result = mgr.authenticate(
            client_host="192.168.99.99",
            token=None,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is False
        assert result.reason == "No authentication provided"

    def test_header_ignored_when_no_trusted_ips_configured(self):
        """C1: Default (no trusted IPs) never trusts proxy headers."""
        mgr = _make_manager()  # no trusted_proxy_ips
        result = mgr.authenticate(
            client_host="10.0.0.1",
            token=None,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is False
        assert result.reason == "No authentication provided"

    def test_header_ignored_with_empty_trusted_ips(self):
        """Explicitly empty set also rejects proxy headers."""
        mgr = _make_manager(trusted_proxy_ips=set())
        result = mgr.authenticate(
            client_host="10.0.0.1",
            token=None,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is False
        assert result.reason == "No authentication provided"

    def test_header_with_unknown_user_from_trusted_proxy_denied(self):
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        result = mgr.authenticate(
            client_host=TRUSTED_PROXY,
            token=None,
            headers={"x-remote-user": "mallory"},
        )
        # Falls through header check (user not in allowed), no token, denied
        assert result.authenticated is False

    def test_token_auth_accepted(self):
        mgr = _make_manager()
        token = mgr.create_session_token("bob")
        result = mgr.authenticate(
            client_host="192.168.1.50",
            token=token,
            headers={},
        )
        assert result.authenticated is True
        assert result.user == "bob"

    def test_token_fallback_when_proxy_header_from_untrusted_ip(self):
        """Token auth still works even when spoofed proxy headers are present."""
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        token = mgr.create_session_token("bob")
        result = mgr.authenticate(
            client_host="192.168.99.99",  # not trusted
            token=token,
            headers={"x-remote-user": "alice"},  # should be ignored
        )
        assert result.authenticated is True
        assert result.user == "bob"  # from token, not header

    def test_localhost_without_token_denied(self):
        """KEY SECURITY CHANGE: localhost no longer auto-authenticates."""
        mgr = _make_manager()
        for host in ("127.0.0.1", "::1", "localhost"):
            result = mgr.authenticate(
                client_host=host,
                token=None,
                headers={},
            )
            assert result.authenticated is False, (
                f"localhost ({host}) should NOT auto-authenticate"
            )
            assert result.reason == "No authentication provided"

    def test_no_auth_at_all_denied(self):
        mgr = _make_manager()
        result = mgr.authenticate(
            client_host="8.8.8.8",
            token=None,
            headers={},
        )
        assert result.authenticated is False
        assert result.reason == "No authentication provided"

    def test_header_takes_priority_over_token_from_trusted_proxy(self):
        """If both header and token are present from trusted proxy, header wins."""
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        token = mgr.create_session_token("bob")
        result = mgr.authenticate(
            client_host=TRUSTED_PROXY,
            token=token,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is True
        assert result.user == "alice"  # header user, not token user

    def test_expired_token_denied(self):
        mgr = _make_manager()
        payload = {"user": "alice", "exp": int(time.time()) - 10}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        import hashlib
        import hmac as hmac_mod

        sig = hmac_mod.new(SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()
        expired_token = f"{payload_b64}.{sig}"

        result = mgr.authenticate(
            client_host="127.0.0.1",
            token=expired_token,
            headers={},
        )
        assert result.authenticated is False
        assert result.reason == "Token expired"

    def test_multiple_trusted_proxies(self):
        """Multiple IPs can be trusted."""
        mgr = _make_manager(trusted_proxy_ips={"10.0.0.1", "10.0.0.2"})
        for ip in ("10.0.0.1", "10.0.0.2"):
            result = mgr.authenticate(
                client_host=ip,
                token=None,
                headers={"x-remote-user": "alice"},
            )
            assert result.authenticated is True, f"Trusted proxy {ip} should be accepted"
            assert result.user == "alice"

    def test_none_client_host_never_trusts_headers(self):
        """If client_host is None, proxy headers are never trusted."""
        mgr = _make_manager(trusted_proxy_ips={TRUSTED_PROXY})
        result = mgr.authenticate(
            client_host=None,
            token=None,
            headers={"x-remote-user": "alice"},
        )
        assert result.authenticated is False
        assert result.reason == "No authentication provided"


# ---------------------------------------------------------------------------
# AuthResult dataclass
# ---------------------------------------------------------------------------


class TestAuthResult:
    def test_defaults(self):
        r = AuthResult(authenticated=False)
        assert r.user is None
        assert r.reason is None

    def test_fields(self):
        r = AuthResult(authenticated=True, user="alice", reason=None)
        assert r.authenticated is True
        assert r.user == "alice"
