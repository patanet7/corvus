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
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

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
