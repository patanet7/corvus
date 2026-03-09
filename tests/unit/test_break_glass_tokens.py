"""Behavioral tests for HMAC-SHA256 break-glass session tokens."""

from __future__ import annotations

import base64
import json
import os
import time

import pytest

from corvus.security.tokens import (
    MIN_SECRET_LEN,
    create_break_glass_token,
    validate_break_glass_token,
)


def _make_secret(length: int = 32) -> bytes:
    """Generate a crypto-random secret of given length."""
    return os.urandom(length)


class TestCreateAndValidateRoundTrip:
    """Token creation followed by validation returns the original claims."""

    def test_round_trip_returns_correct_payload(self) -> None:
        secret = _make_secret()
        token = create_break_glass_token(
            secret=secret,
            agent_name="homelab",
            session_id="sess-abc-123",
            ttl_seconds=300,
        )
        payload = validate_break_glass_token(secret=secret, token=token)
        assert payload["agent_name"] == "homelab"
        assert payload["session_id"] == "sess-abc-123"
        assert "exp" in payload

    def test_token_contains_expected_fields(self) -> None:
        secret = _make_secret()
        token = create_break_glass_token(
            secret=secret,
            agent_name="finance",
            session_id="sess-xyz-789",
            ttl_seconds=60,
        )
        payload = validate_break_glass_token(secret=secret, token=token)
        assert set(payload.keys()) == {"agent_name", "session_id", "exp"}

    def test_token_bound_to_specific_agent_and_session(self) -> None:
        secret = _make_secret()
        token = create_break_glass_token(
            secret=secret,
            agent_name="work",
            session_id="sess-work-001",
            ttl_seconds=120,
        )
        payload = validate_break_glass_token(secret=secret, token=token)
        assert payload["agent_name"] == "work"
        assert payload["session_id"] == "sess-work-001"

    def test_expiry_is_in_the_future(self) -> None:
        secret = _make_secret()
        before = int(time.time())
        token = create_break_glass_token(
            secret=secret,
            agent_name="test",
            session_id="sess-1",
            ttl_seconds=600,
        )
        payload = validate_break_glass_token(secret=secret, token=token)
        assert payload["exp"] >= before + 600


class TestExpiredToken:
    """Expired tokens must be rejected."""

    def test_expired_token_raises_value_error(self) -> None:
        secret = _make_secret()
        token = create_break_glass_token(
            secret=secret,
            agent_name="homelab",
            session_id="sess-exp",
            ttl_seconds=1,
        )
        time.sleep(1.1)
        with pytest.raises(ValueError, match="expired"):
            validate_break_glass_token(secret=secret, token=token)


class TestWrongSecret:
    """Tokens validated with a different secret must be rejected."""

    def test_wrong_secret_raises_value_error(self) -> None:
        secret_a = _make_secret()
        secret_b = _make_secret()
        token = create_break_glass_token(
            secret=secret_a,
            agent_name="homelab",
            session_id="sess-wrong",
            ttl_seconds=300,
        )
        with pytest.raises(ValueError, match="signature"):
            validate_break_glass_token(secret=secret_b, token=token)


class TestTamperedPayload:
    """Tokens with modified payloads must be rejected."""

    def test_tampered_payload_raises_value_error(self) -> None:
        secret = _make_secret()
        token = create_break_glass_token(
            secret=secret,
            agent_name="homelab",
            session_id="sess-tamper",
            ttl_seconds=300,
        )
        payload_b64, sig = token.split(".")
        # Decode, modify, re-encode the payload
        raw = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        raw["agent_name"] = "hacked"
        tampered_b64 = (
            base64.urlsafe_b64encode(json.dumps(raw).encode())
            .rstrip(b"=")
            .decode("ascii")
        )
        tampered_token = f"{tampered_b64}.{sig}"
        with pytest.raises(ValueError, match="signature"):
            validate_break_glass_token(secret=secret, token=tampered_token)


class TestShortSecret:
    """Secrets shorter than MIN_SECRET_LEN must be rejected."""

    def test_create_with_short_secret_raises(self) -> None:
        short_secret = os.urandom(MIN_SECRET_LEN - 1)
        with pytest.raises(ValueError, match=str(MIN_SECRET_LEN)):
            create_break_glass_token(
                secret=short_secret,
                agent_name="test",
                session_id="sess-1",
                ttl_seconds=60,
            )

    def test_validate_with_short_secret_raises(self) -> None:
        good_secret = _make_secret()
        token = create_break_glass_token(
            secret=good_secret,
            agent_name="test",
            session_id="sess-1",
            ttl_seconds=60,
        )
        short_secret = os.urandom(MIN_SECRET_LEN - 1)
        with pytest.raises(ValueError, match=str(MIN_SECRET_LEN)):
            validate_break_glass_token(secret=short_secret, token=token)


class TestInvalidTokenFormat:
    """Malformed token strings must be rejected."""

    def test_no_dot_separator_raises(self) -> None:
        secret = _make_secret()
        with pytest.raises(ValueError, match="format"):
            validate_break_glass_token(secret=secret, token="nodots")

    def test_too_many_parts_raises(self) -> None:
        secret = _make_secret()
        with pytest.raises(ValueError, match="format"):
            validate_break_glass_token(secret=secret, token="a.b.c")


class TestNonPositiveTTL:
    """TTL must be positive."""

    def test_zero_ttl_raises(self) -> None:
        secret = _make_secret()
        with pytest.raises(ValueError, match="positive"):
            create_break_glass_token(
                secret=secret,
                agent_name="test",
                session_id="s",
                ttl_seconds=0,
            )

    def test_negative_ttl_raises(self) -> None:
        secret = _make_secret()
        with pytest.raises(ValueError, match="positive"):
            create_break_glass_token(
                secret=secret,
                agent_name="test",
                session_id="s",
                ttl_seconds=-10,
            )
