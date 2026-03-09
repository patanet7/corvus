"""HMAC-SHA256 break-glass session tokens.

Tokens are bound to agent_name + session_id with TTL expiry.
The signing secret must be crypto-random, at least 32 bytes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

MIN_SECRET_LEN = 32


def _b64encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_break_glass_token(
    *,
    secret: bytes,
    agent_name: str,
    session_id: str,
    ttl_seconds: int,
) -> str:
    """Create a signed, time-limited break-glass token.

    Args:
        secret: Random bytes for HMAC signing (>= 32 bytes).
        agent_name: Agent name bound into the token.
        session_id: Session identifier bound into the token.
        ttl_seconds: Seconds until the token expires (must be positive).

    Returns:
        Signed token string in payload.signature format.

    Raises:
        ValueError: If secret is too short or ttl_seconds is not positive.
    """
    if len(secret) < MIN_SECRET_LEN:
        raise ValueError(f"Secret must be at least {MIN_SECRET_LEN} bytes")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    payload = {
        "agent_name": agent_name,
        "session_id": session_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_b64 = _b64encode(json.dumps(payload).encode())
    sig = _b64encode(hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest())
    return f"{payload_b64}.{sig}"


def validate_break_glass_token(*, secret: bytes, token: str) -> dict:
    """Validate and decode a break-glass token.

    Args:
        secret: The same secret used to create the token.
        token: The token string to validate.

    Returns:
        The decoded payload dict with keys: agent_name, session_id, exp.

    Raises:
        ValueError: If the token is malformed, has an invalid signature, or is expired.
    """
    if len(secret) < MIN_SECRET_LEN:
        raise ValueError(f"Secret must be at least {MIN_SECRET_LEN} bytes")

    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid token format")

    payload_b64, sig_b64 = parts

    # Verify signature (timing-safe comparison)
    expected_sig = _b64encode(
        hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid token signature")

    # Decode payload
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception as exc:
        raise ValueError(f"Malformed token payload: {exc}") from exc

    # Check expiry
    if payload.get("exp", 0) < time.time():
        raise ValueError("Token expired")

    return payload
