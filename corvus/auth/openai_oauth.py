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
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


logger = logging.getLogger(__name__)


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
    except (IndexError, json.JSONDecodeError, Exception):
        logger.warning("Failed to decode account_id from JWT")
        return ""


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

    req = Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Token exchange failed: HTTP {resp.status}")
        data = json.loads(resp.read())

    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 3600)
    expires = int(time.time()) + expires_in
    account_id = decode_jwt_account_id(access_token)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires=expires,
        account_id=account_id,
    )
