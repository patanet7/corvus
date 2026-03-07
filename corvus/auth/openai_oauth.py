"""OpenAI PKCE OAuth flow for Codex/ChatGPT subscription auth.

Handles the full OAuth flow:
1. PKCE generation (code_verifier + code_challenge)
2. Local callback server on 127.0.0.1:1455
3. Browser-based authorization
4. Token exchange at auth.openai.com/oauth/token
5. JWT decode for account_id extraction
6. Token refresh
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

OPENAI_AUTH_BASE = "https://auth.openai.com"
OPENAI_AUTHORIZE_URL = f"{OPENAI_AUTH_BASE}/oauth/authorize"
OPENAI_TOKEN_URL = f"{OPENAI_AUTH_BASE}/oauth/token"
CODEX_CLIENT_ID = "app_codex"
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"


@dataclass(frozen=True)
class PkceParams:
    """PKCE parameters for OAuth authorization."""

    verifier: str
    challenge: str
    state: str


@dataclass(frozen=True)
class OAuthTokens:
    """Tokens returned from OAuth token exchange or refresh."""

    access_token: str
    refresh_token: str
    expires: int
    account_id: str


def generate_pkce() -> PkceParams:
    """Generate PKCE code_verifier, code_challenge (S256), and state."""
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")

    challenge_digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(challenge_digest).rstrip(b"=").decode("ascii")

    state = secrets.token_urlsafe(24)

    return PkceParams(verifier=verifier, challenge=challenge, state=state)


def build_authorize_url(pkce: PkceParams) -> str:
    """Build the OpenAI OAuth authorization URL with PKCE params."""
    params = {
        "response_type": "code",
        "client_id": CODEX_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "state": pkce.state,
        "scope": "openid profile email offline_access",
    }
    return f"{OPENAI_AUTHORIZE_URL}?{urlencode(params)}"


def decode_jwt_account_id(token: str) -> str:
    """Extract chatgpt_account_id from an OpenAI access token JWT.

    Decodes the payload segment (no signature verification — we trust
    the token endpoint response). Returns empty string if the claim
    is missing.
    """
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("https://api.openai.com/auth", {}).get("chatgpt_account_id", "")
    except (IndexError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Failed to decode account_id from JWT")
        return ""


def _post_token_request(
    *,
    body: bytes,
    token_url: str,
    error_prefix: str,
    fallback_refresh: str = "",
) -> OAuthTokens:
    """POST to the OpenAI token endpoint and return parsed OAuthTokens.

    Args:
        body: URL-encoded form body bytes.
        token_url: The token endpoint URL.
        error_prefix: Human-readable prefix for error messages.
        fallback_refresh: Refresh token to use when the response omits one.

    Returns:
        OAuthTokens with access_token, refresh_token, expires, account_id.

    Raises:
        RuntimeError: If the request or response parsing fails.
    """
    req = Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{error_prefix}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{error_prefix}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{error_prefix}: invalid JSON response") from exc

    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"{error_prefix}: no access_token in response")
    refresh_token = data.get("refresh_token", fallback_refresh)
    expires_in = data.get("expires_in", 3600)
    expires = int(time.time()) + expires_in
    account_id = decode_jwt_account_id(access_token)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires=expires,
        account_id=account_id,
    )


def exchange_code_for_tokens(
    *,
    code: str,
    verifier: str,
    token_url: str = OPENAI_TOKEN_URL,
) -> OAuthTokens:
    """Exchange an authorization code for OAuth tokens.

    Args:
        code: The authorization code from the callback.
        verifier: The PKCE code_verifier used in the authorize request.
        token_url: The token endpoint URL (override for testing).

    Returns:
        OAuthTokens with access_token, refresh_token, expires, account_id.

    Raises:
        RuntimeError: If the token exchange fails.
    """
    body = urlencode({
        "grant_type": "authorization_code",
        "client_id": CODEX_CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode("utf-8")

    return _post_token_request(
        body=body,
        token_url=token_url,
        error_prefix="Token exchange failed",
    )


def refresh_access_token(
    *,
    refresh_token: str,
    token_url: str = OPENAI_TOKEN_URL,
) -> OAuthTokens:
    """Refresh an expired access token using the refresh_token grant.

    Args:
        refresh_token: The refresh token from a previous exchange.
        token_url: The token endpoint URL (override for testing).

    Returns:
        OAuthTokens with fresh access_token, refresh_token, expires, account_id.

    Raises:
        RuntimeError: If the refresh fails.
    """
    body = urlencode({
        "grant_type": "refresh_token",
        "client_id": CODEX_CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode("utf-8")

    return _post_token_request(
        body=body,
        token_url=token_url,
        error_prefix="Token refresh failed",
        fallback_refresh=refresh_token,
    )
