"""Tests for agent-scoped JWT tokens."""

import json
import time

import pytest

from corvus.cli.tool_token import _b64encode, create_token, validate_token

TEST_SECRET = b"test-secret-32-bytes-long-enough"


class TestCreateToken:
    """Tests for JWT creation."""

    def test_creates_token_string(self) -> None:
        """create_token returns a non-empty string."""
        token = create_token(
            secret=TEST_SECRET,
            agent="personal",
            modules=["obsidian", "memory"],
            ttl_seconds=3600,
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_three_base64_parts(self) -> None:
        """Token has header.payload.signature format."""
        token = create_token(
            secret=TEST_SECRET,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        parts = token.split(".")
        assert len(parts) == 3

    def test_rejects_short_secret(self) -> None:
        """create_token rejects secrets shorter than 32 bytes."""
        with pytest.raises(ValueError, match="secret must be >= 32 bytes"):
            create_token(
                secret=b"too-short",
                agent="personal",
                modules=["obsidian"],
                ttl_seconds=3600,
            )

    def test_rejects_non_positive_ttl(self) -> None:
        """create_token rejects zero or negative ttl_seconds."""
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            create_token(
                secret=TEST_SECRET,
                agent="personal",
                modules=["obsidian"],
                ttl_seconds=0,
            )
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            create_token(
                secret=TEST_SECRET,
                agent="personal",
                modules=["obsidian"],
                ttl_seconds=-1,
            )


class TestValidateToken:
    """Tests for JWT validation."""

    def test_valid_token_returns_payload(self) -> None:
        """A freshly created token validates successfully."""
        token = create_token(
            secret=TEST_SECRET,
            agent="personal",
            modules=["obsidian", "email"],
            ttl_seconds=3600,
        )
        payload = validate_token(secret=TEST_SECRET, token=token)
        assert payload["agent"] == "personal"
        assert payload["modules"] == ["obsidian", "email"]

    def test_expired_token_raises(self) -> None:
        """An expired token raises ValueError."""
        # Construct a token with exp in the past without using create_token
        # (since create_token now rejects ttl_seconds <= 0).
        header = _b64encode(json.dumps({"alg": "HS256", "typ": "CVT"}).encode())
        payload_dict = {
            "agent": "personal",
            "modules": ["obsidian"],
            "exp": int(time.time()) - 10,
        }
        payload = _b64encode(json.dumps(payload_dict).encode())
        import hashlib
        import hmac as hmac_mod

        signing_input = f"{header}.{payload}".encode()
        sig = _b64encode(hmac_mod.new(TEST_SECRET, signing_input, hashlib.sha256).digest())
        token = f"{header}.{payload}.{sig}"

        with pytest.raises(ValueError, match="expired"):
            validate_token(secret=TEST_SECRET, token=token)

    def test_wrong_secret_raises(self) -> None:
        """Token signed with different secret is rejected."""
        secret_a = b"secret-a-32-bytes-long-enough!!ab"
        secret_b = b"secret-b-32-bytes-long-enough!!ab"
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
        token = create_token(
            secret=TEST_SECRET,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # reverse the payload
        tampered = ".".join(parts)
        with pytest.raises(ValueError):
            validate_token(secret=TEST_SECRET, token=tampered)

    def test_modules_list_preserved(self) -> None:
        """Modules list in payload matches what was signed."""
        modules = ["ha", "obsidian", "email", "memory"]
        token = create_token(
            secret=TEST_SECRET,
            agent="homelab",
            modules=modules,
            ttl_seconds=3600,
        )
        payload = validate_token(secret=TEST_SECRET, token=token)
        assert payload["modules"] == modules

    def test_rejects_short_secret_on_validate(self) -> None:
        """validate_token rejects secrets shorter than 32 bytes."""
        token = create_token(
            secret=TEST_SECRET,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        with pytest.raises(ValueError, match="secret must be >= 32 bytes"):
            validate_token(secret=b"short", token=token)
