"""Session authentication for WebSocket connections.

Replaces localhost auto-auth with signed session tokens.
Uses HMAC-SHA256 for token signing, consistent with the existing
break-glass token pattern in corvus.security.tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

MIN_SECRET_LEN = 32


@dataclass
class AuthResult:
    """Result of an authentication attempt."""

    authenticated: bool
    user: str | None = None
    reason: str | None = None


class SessionAuthManager:
    """Manages session token creation and validation for WebSocket auth.

    Tokens are HMAC-SHA256 signed JSON payloads containing user identity
    and expiration. This replaces the previous localhost auto-auth pattern
    where any local process could connect with full user privileges.
    """

    def __init__(
        self,
        *,
        secret: bytes,
        allowed_users: list[str],
        trusted_proxy_ips: set[str] | None = None,
    ) -> None:
        if len(secret) < MIN_SECRET_LEN:
            raise ValueError(f"Secret must be at least {MIN_SECRET_LEN} bytes")
        self._secret = secret
        self._allowed_users = set(allowed_users)
        self._trusted_proxy_ips = trusted_proxy_ips or set()

    def create_session_token(self, user: str, ttl_seconds: int = 86400) -> str:
        """Create a signed session token for a user.

        Args:
            user: Username to embed in the token. Must be in allowed_users.
            ttl_seconds: Token lifetime in seconds (default 24h).

        Returns:
            Signed token string in ``payload_b64.signature_hex`` format.

        Raises:
            ValueError: If user is not in allowed_users or ttl is not positive.
        """
        if user not in self._allowed_users:
            raise ValueError(f"User {user!r} not in allowed users")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        payload = {
            "user": user,
            "exp": int(time.time()) + ttl_seconds,
        }
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        sig = hmac.new(self._secret, payload_b64.encode(), hashlib.sha256).hexdigest()
        return f"{payload_b64}.{sig}"

    def validate_session_token(self, token: str) -> AuthResult:
        """Validate a session token and return AuthResult.

        Performs timing-safe signature comparison and checks expiry
        and user membership.
        """
        parts = token.split(".")
        if len(parts) != 2:
            return AuthResult(authenticated=False, reason="Invalid token format")

        payload_b64, sig = parts

        # Timing-safe signature comparison
        expected_sig = hmac.new(
            self._secret, payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return AuthResult(authenticated=False, reason="Invalid signature")

        try:
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:
            return AuthResult(authenticated=False, reason="Invalid payload")

        if payload.get("exp", 0) < time.time():
            return AuthResult(authenticated=False, reason="Token expired")

        user = payload.get("user")
        if user not in self._allowed_users:
            return AuthResult(authenticated=False, reason="User not allowed")

        return AuthResult(authenticated=True, user=user)

    def authenticate(
        self,
        *,
        client_host: str | None,
        token: str | None,
        headers: dict[str, str],
    ) -> AuthResult:
        """Authenticate a WebSocket connection.

        Priority:
        1. Trusted reverse-proxy headers (X-Remote-User / Remote-User) --
           only accepted when client_host is in trusted_proxy_ips.
        2. Session token (query param or header)
        3. Deny -- no more localhost auto-auth

        Args:
            client_host: Remote IP of the connecting client. Used to gate
                proxy header trust and for audit logging.
            token: Session token from query params or Authorization header.
            headers: HTTP headers dict (keys should be lowercase).

        Returns:
            AuthResult indicating success/failure with user or reason.
        """
        # 1. Trusted headers -- ONLY from trusted proxy IPs
        if client_host and client_host in self._trusted_proxy_ips:
            user = headers.get("x-remote-user") or headers.get("remote-user")
            if user and user in self._allowed_users:
                return AuthResult(authenticated=True, user=user)

        # 2. Session token
        if token:
            return self.validate_session_token(token)

        # 3. No auth — deny (no more localhost auto-auth)
        return AuthResult(authenticated=False, reason="No authentication provided")
