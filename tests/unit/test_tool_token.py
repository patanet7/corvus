"""Tests for agent-scoped JWT tokens."""

import time

import pytest

from corvus.cli.tool_token import create_token, validate_token


class TestCreateToken:
    """Tests for JWT creation."""

    def test_creates_token_string(self) -> None:
        """create_token returns a non-empty string."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian", "memory"],
            ttl_seconds=3600,
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_three_base64_parts(self) -> None:
        """Token has header.payload.signature format."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        parts = token.split(".")
        assert len(parts) == 3


class TestValidateToken:
    """Tests for JWT validation."""

    def test_valid_token_returns_payload(self) -> None:
        """A freshly created token validates successfully."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian", "email"],
            ttl_seconds=3600,
        )
        payload = validate_token(secret=secret, token=token)
        assert payload["agent"] == "personal"
        assert payload["modules"] == ["obsidian", "email"]

    def test_expired_token_raises(self) -> None:
        """An expired token raises ValueError."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=-1,  # already expired
        )
        with pytest.raises(ValueError, match="expired"):
            validate_token(secret=secret, token=token)

    def test_wrong_secret_raises(self) -> None:
        """Token signed with different secret is rejected."""
        secret_a = b"secret-a-32-bytes-long-enough!!"
        secret_b = b"secret-b-32-bytes-long-enough!!"
        token = create_token(
            secret=secret_a,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        with pytest.raises(ValueError, match="signature"):
            validate_token(secret=secret_b, token=token)

    def test_tampered_payload_raises(self) -> None:
        """Token with modified payload is rejected."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        # Tamper with the payload portion
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # reverse the payload
        tampered = ".".join(parts)
        with pytest.raises(ValueError):
            validate_token(secret=secret, token=tampered)

    def test_modules_list_preserved(self) -> None:
        """Modules list in payload matches what was signed."""
        secret = b"test-secret-32-bytes-long-enough"
        modules = ["ha", "obsidian", "email", "memory"]
        token = create_token(
            secret=secret,
            agent="homelab",
            modules=modules,
            ttl_seconds=3600,
        )
        payload = validate_token(secret=secret, token=token)
        assert payload["modules"] == modules
