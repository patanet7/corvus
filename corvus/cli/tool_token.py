"""Agent-scoped JWT tokens for the corvus tool server.

Tokens are HMAC-SHA256 signed JSON payloads with:
- agent: the agent name
- modules: list of allowed tool module names
- exp: Unix timestamp expiry

Tokens use a custom minimal format (not a full JWT library)
to avoid adding dependencies. Format: base64(header).base64(payload).base64(signature)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(
    *,
    secret: bytes,
    agent: str,
    modules: list[str],
    ttl_seconds: int,
) -> str:
    """Create an agent-scoped token.

    Args:
        secret: Random bytes for HMAC signing (>= 32 bytes recommended).
        agent: Agent name baked into the token.
        modules: List of allowed tool module names.
        ttl_seconds: Seconds until the token expires.

    Returns:
        Signed token string in header.payload.signature format.
    """
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "CVT"}).encode())
    payload_dict = {
        "agent": agent,
        "modules": modules,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64encode(json.dumps(payload_dict).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = _b64encode(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def validate_token(*, secret: bytes, token: str) -> dict:
    """Validate a token and return its payload.

    Args:
        secret: The same secret used to create the token.
        token: The token string to validate.

    Returns:
        The decoded payload dict with keys: agent, modules, exp.

    Raises:
        ValueError: If the token is malformed, expired, or has an invalid signature.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token: expected 3 parts")

    header_b64, payload_b64, signature_b64 = parts

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64decode(signature_b64)
    except Exception as exc:
        raise ValueError(f"malformed signature: {exc}") from exc

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("invalid signature")

    # Decode payload
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception as exc:
        raise ValueError(f"malformed payload: {exc}") from exc

    # Check expiry
    exp = payload.get("exp", 0)
    if time.time() > exp:
        raise ValueError("token expired")

    return payload
