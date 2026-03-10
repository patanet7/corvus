---
title: "ACP Auth Integration Implementation Plan"
type: plan
status: implemented
date: 2026-03-06
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# ACP Auth Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run OpenAI PKCE OAuth flow, store tokens in SOPS credential store, refresh at runtime, inject into ACP spawn env.

**Architecture:** New `corvus/auth/openai_oauth.py` handles the OAuth flow (PKCE, local callback server, token exchange, JWT decode, refresh). Credential store gets a `"codex"` service with `{access_token, refresh_token, expires, account_id}`. `inject()` refreshes if expired and sets `CODEX_API_KEY`. Setup wizard gets a Codex backend option that triggers OAuth instead of collecting a text key.

**Tech Stack:** Python stdlib only (http.server, urllib.request, hashlib, secrets, json, webbrowser, base64). SOPS+age for credential storage. Textual for setup TUI.

**Design doc:** `docs/plans/2026-03-06-acp-auth-integration-design.md`

---

### Task 1: PKCE Helper Functions

**Files:**
- Create: `corvus/auth/__init__.py`
- Create: `corvus/auth/openai_oauth.py`
- Create: `tests/unit/test_openai_oauth.py`

**Step 1: Write the failing tests**

```python
"""Behavioral tests for corvus.auth.openai_oauth — PKCE helpers."""

import base64
import hashlib

from corvus.auth.openai_oauth import generate_pkce, build_authorize_url


class TestGeneratePkce:
    """Tests for PKCE code_verifier and code_challenge generation."""

    def test_verifier_length(self) -> None:
        """Verifier must be 43-128 chars per RFC 7636."""
        pkce = generate_pkce()
        assert 43 <= len(pkce.verifier) <= 128

    def test_verifier_is_url_safe(self) -> None:
        """Verifier must be URL-safe base64 characters only."""
        pkce = generate_pkce()
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert all(c in allowed for c in pkce.verifier)

    def test_challenge_matches_verifier(self) -> None:
        """Challenge must be SHA256(verifier) base64url-encoded."""
        pkce = generate_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(pkce.verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert pkce.challenge == expected

    def test_state_is_nonempty(self) -> None:
        """State must be a nonempty random string."""
        pkce = generate_pkce()
        assert len(pkce.state) >= 16


class TestBuildAuthorizeUrl:
    """Tests for OAuth authorize URL construction."""

    def test_url_contains_required_params(self) -> None:
        """URL must contain client_id, redirect_uri, code_challenge, state."""
        pkce = generate_pkce()
        url = build_authorize_url(pkce)
        assert "auth.openai.com" in url
        assert "code_challenge=" in url
        assert "state=" + pkce.state in url
        assert "code_challenge_method=S256" in url
        assert "redirect_uri=" in url
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py -v`
Expected: FAIL with ImportError (module doesn't exist)

**Step 3: Write minimal implementation**

`corvus/auth/__init__.py`:
```python
"""Auth module — OAuth flows and token management for external providers."""
```

`corvus/auth/openai_oauth.py`:
```python
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add corvus/auth/__init__.py corvus/auth/openai_oauth.py tests/unit/test_openai_oauth.py
git commit -m "feat: add PKCE helper functions for OpenAI OAuth"
```

---

### Task 2: Token Exchange and JWT Decode

**Files:**
- Modify: `corvus/auth/openai_oauth.py`
- Modify: `tests/unit/test_openai_oauth.py`

**Step 1: Write the failing tests**

Add to `tests/unit/test_openai_oauth.py`:

```python
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from corvus.auth.openai_oauth import (
    exchange_code_for_tokens,
    decode_jwt_account_id,
    OAuthTokens,
)


def _make_fake_jwt(payload: dict) -> str:
    """Build a fake JWT (header.payload.signature) for testing."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


class TestDecodeJwtAccountId:
    """Tests for JWT account_id extraction."""

    def test_extracts_account_id(self) -> None:
        """Must extract chatgpt_account_id from OpenAI JWT claims."""
        token = _make_fake_jwt({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc_abc123"},
            "sub": "user123",
        })
        assert decode_jwt_account_id(token) == "acc_abc123"

    def test_returns_empty_on_missing_claim(self) -> None:
        """Must return empty string if claim is missing."""
        token = _make_fake_jwt({"sub": "user123"})
        assert decode_jwt_account_id(token) == ""


class TestExchangeCodeForTokens:
    """Tests for OAuth token exchange against a fake token endpoint."""

    def test_exchanges_code_successfully(self) -> None:
        """Must POST to token endpoint and return OAuthTokens."""
        fake_access = _make_fake_jwt({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc_test"},
        })
        response_body = json.dumps({
            "access_token": fake_access,
            "refresh_token": "refresh_xyz",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()

        try:
            result = exchange_code_for_tokens(
                code="test_code",
                verifier="test_verifier",
                token_url=f"http://127.0.0.1:{port}/oauth/token",
            )
        finally:
            server.server_close()
            thread.join(timeout=2)

        assert isinstance(result, OAuthTokens)
        assert result.access_token == fake_access
        assert result.refresh_token == "refresh_xyz"
        assert result.account_id == "acc_test"
        assert result.expires > int(time.time())
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py -v`
Expected: FAIL with ImportError for `exchange_code_for_tokens`, `decode_jwt_account_id`

**Step 3: Write minimal implementation**

Add to `corvus/auth/openai_oauth.py`:

```python
import json
import logging
import time
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def decode_jwt_account_id(token: str) -> str:
    """Extract chatgpt_account_id from an OpenAI access token JWT.

    Decodes the payload segment (no signature verification — we trust
    the token endpoint response). Returns empty string if the claim
    is missing.
    """
    try:
        payload_b64 = token.split(".")[1]
        # Add padding
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add corvus/auth/openai_oauth.py tests/unit/test_openai_oauth.py
git commit -m "feat: add token exchange and JWT decode for OpenAI OAuth"
```

---

### Task 3: Token Refresh

**Files:**
- Modify: `corvus/auth/openai_oauth.py`
- Modify: `tests/unit/test_openai_oauth.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_openai_oauth.py`:

```python
from corvus.auth.openai_oauth import refresh_access_token


class TestRefreshAccessToken:
    """Tests for OAuth token refresh."""

    def test_refresh_returns_new_tokens(self) -> None:
        """Must POST to token endpoint with refresh_token grant and return new tokens."""
        new_access = _make_fake_jwt({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc_refreshed"},
        })
        response_body = json.dumps({
            "access_token": new_access,
            "refresh_token": "new_refresh_xyz",
            "expires_in": 7200,
        }).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()

        try:
            result = refresh_access_token(
                refresh_token="old_refresh",
                token_url=f"http://127.0.0.1:{port}/oauth/token",
            )
        finally:
            server.server_close()
            thread.join(timeout=2)

        assert result.access_token == new_access
        assert result.refresh_token == "new_refresh_xyz"
        assert result.account_id == "acc_refreshed"
        assert result.expires > int(time.time())
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py::TestRefreshAccessToken -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `corvus/auth/openai_oauth.py`:

```python
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

    req = Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Token refresh failed: HTTP {resp.status}")
        data = json.loads(resp.read())

    access_token = data["access_token"]
    new_refresh = data.get("refresh_token", refresh_token)
    expires_in = data.get("expires_in", 3600)
    expires = int(time.time()) + expires_in
    account_id = decode_jwt_account_id(access_token)

    return OAuthTokens(
        access_token=access_token,
        refresh_token=new_refresh,
        expires=expires,
        account_id=account_id,
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add corvus/auth/openai_oauth.py tests/unit/test_openai_oauth.py
git commit -m "feat: add token refresh for OpenAI OAuth"
```

---

### Task 4: Local Callback Server + Full OAuth Flow

**Files:**
- Modify: `corvus/auth/openai_oauth.py`
- Modify: `tests/unit/test_openai_oauth.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_openai_oauth.py`:

```python
from urllib.request import urlopen as stdlib_urlopen

from corvus.auth.openai_oauth import run_callback_server


class TestRunCallbackServer:
    """Tests for the local OAuth callback server."""

    def test_captures_code_and_state(self) -> None:
        """Server must capture code and state from callback URL params."""
        server, get_result = run_callback_server(port=0)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()

        # Simulate browser callback
        stdlib_urlopen(
            f"http://127.0.0.1:{port}/auth/callback?code=test_auth_code&state=test_state",
            timeout=5,
        )
        thread.join(timeout=2)
        server.server_close()

        result = get_result()
        assert result["code"] == "test_auth_code"
        assert result["state"] == "test_state"
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py::TestRunCallbackServer -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `corvus/auth/openai_oauth.py`:

```python
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

CALLBACK_PORT = 1455


def run_callback_server(
    *,
    port: int = CALLBACK_PORT,
) -> tuple[HTTPServer, Any]:
    """Start a local HTTP server to capture the OAuth callback.

    Returns:
        A tuple of (server, get_result) where get_result() returns
        {"code": ..., "state": ...} after the callback is received.
    """
    captured: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            captured["code"] = params.get("code", [""])[0]
            captured["state"] = params.get("state", [""])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication successful</h1>"
                b"<p>You can close this window.</p></body></html>"
            )

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)

    def get_result() -> dict[str, str]:
        return captured

    return server, get_result
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_openai_oauth.py -v`
Expected: 9 PASSED

**Step 5: Commit**

```bash
git add corvus/auth/openai_oauth.py tests/unit/test_openai_oauth.py
git commit -m "feat: add local callback server for OpenAI OAuth"
```

---

### Task 5: Credential Store — Codex inject() and refresh

**Files:**
- Modify: `corvus/credential_store.py:117-160` (inject method)
- Modify: `corvus/credential_store.py:210-231` (from_env env_map)
- Create: `tests/unit/test_credential_store_codex.py`

**Step 1: Write the failing tests**

```python
"""Behavioral tests for credential store Codex OAuth integration."""

import os
import time

from corvus.credential_store import CredentialStore


class TestCredentialStoreCodexInject:
    """Tests for inject() handling the codex service."""

    def test_inject_sets_codex_api_key_from_valid_token(self) -> None:
        """inject() must set CODEX_API_KEY when codex tokens are not expired."""
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {
            "codex": {
                "access_token": "valid_access_token",
                "refresh_token": "some_refresh",
                "expires": str(int(time.time()) + 3600),
                "account_id": "acc_123",
            }
        }

        env_before = os.environ.get("CODEX_API_KEY")
        try:
            store.inject()
            assert os.environ["CODEX_API_KEY"] == "valid_access_token"
        finally:
            if env_before is None:
                os.environ.pop("CODEX_API_KEY", None)
            else:
                os.environ["CODEX_API_KEY"] = env_before

    def test_inject_skips_codex_when_not_configured(self) -> None:
        """inject() must not set CODEX_API_KEY when codex is not in store."""
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}

        env_before = os.environ.get("CODEX_API_KEY")
        try:
            os.environ.pop("CODEX_API_KEY", None)
            store.inject()
            assert "CODEX_API_KEY" not in os.environ
        finally:
            if env_before is not None:
                os.environ["CODEX_API_KEY"] = env_before


class TestFromEnvCodex:
    """Tests for from_env() picking up CODEX_API_KEY."""

    def test_from_env_captures_codex_key(self) -> None:
        """from_env() must populate codex service from CODEX_API_KEY env var."""
        env_before = os.environ.get("CODEX_API_KEY")
        try:
            os.environ["CODEX_API_KEY"] = "test_codex_key"
            store = CredentialStore.from_env()
            assert store.get("codex", "access_token") == "test_codex_key"
        finally:
            if env_before is None:
                os.environ.pop("CODEX_API_KEY", None)
            else:
                os.environ["CODEX_API_KEY"] = env_before
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_credential_store_codex.py -v`
Expected: FAIL (inject doesn't handle codex, from_env doesn't map CODEX_API_KEY)

**Step 3: Modify credential_store.py**

Add to `inject()` method, after the OpenAI block (after line 139):

```python
        # Codex (ChatGPT OAuth) -- inject access token, refresh if expired
        if "codex" in self._data:
            codex = self._data["codex"]
            access = codex.get("access_token", "")
            expires = int(codex.get("expires", "0"))
            if access and expires > int(time.time()):
                os.environ["CODEX_API_KEY"] = access
            elif codex.get("refresh_token"):
                try:
                    from corvus.auth.openai_oauth import refresh_access_token

                    tokens = refresh_access_token(refresh_token=codex["refresh_token"])
                    self._data["codex"]["access_token"] = tokens.access_token
                    self._data["codex"]["refresh_token"] = tokens.refresh_token
                    self._data["codex"]["expires"] = str(tokens.expires)
                    self._data["codex"]["account_id"] = tokens.account_id
                    os.environ["CODEX_API_KEY"] = tokens.access_token
                    if self._path is not None:
                        self._save()
                except Exception:
                    logger.warning("Failed to refresh Codex OAuth token")
```

Add `import time` and `import logging` + `logger = logging.getLogger(__name__)` at the top of the file.

Add to `from_env()` env_map (after the webhook_secret entry):

```python
            "codex": {"access_token": "CODEX_API_KEY"},
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_credential_store_codex.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add corvus/credential_store.py tests/unit/test_credential_store_codex.py
git commit -m "feat: add Codex OAuth token inject and refresh to credential store"
```

---

### Task 6: Setup Wizard — Codex Backend with OAuth Button

**Files:**
- Modify: `corvus/cli/screens/backends.py:14-52` (BACKENDS list)
- Modify: `corvus/cli/screens/backends.py:55-84` (_validate_backend)
- Modify: `corvus/cli/screens/backends.py:87-161` (ModelBackendsScreen class)
- Modify: `corvus/cli/setup.py:76-98` (_save_credentials)

**Step 1: Modify backends.py**

Add Codex to the BACKENDS list (after the `openai` entry):

```python
    (
        "codex",
        "OpenAI Codex (ChatGPT subscription)",
        [],  # No text fields — uses OAuth button
    ),
```

Add Codex validation (no-op since OAuth handles it):

```python
    if backend_id == "codex":
        return True, ""
```

Modify `ModelBackendsScreen.compose()` to add an OAuth button when the codex toggle is enabled. After the fields loop, check if backend_id is "codex" and yield a Button:

```python
                if backend_id == "codex":
                    yield Button(
                        "Sign in with ChatGPT",
                        id="codex-oauth-btn",
                        variant="success",
                    )
                    yield Static("", id="codex-oauth-status")
```

Add a handler for the OAuth button:

```python
    def _run_codex_oauth(self) -> None:
        """Run the Codex OAuth flow in a background thread."""
        import webbrowser
        from threading import Thread

        from corvus.auth.openai_oauth import (
            build_authorize_url,
            exchange_code_for_tokens,
            generate_pkce,
            run_callback_server,
        )

        status = self.query_one("#codex-oauth-status", Static)
        status.update("Starting OAuth flow...")

        pkce = generate_pkce()
        server, get_result = run_callback_server()

        def _flow():
            url = build_authorize_url(pkce)
            webbrowser.open(url)
            server.handle_request()
            server.server_close()
            result = get_result()
            if result.get("code") and result.get("state") == pkce.state:
                try:
                    tokens = exchange_code_for_tokens(
                        code=result["code"], verifier=pkce.verifier,
                    )
                    self.app._codex_tokens = tokens  # type: ignore[attr-defined]
                    self.app.call_from_thread(
                        status.update, "Authenticated successfully!"
                    )
                except Exception as exc:
                    self.app.call_from_thread(
                        status.update, f"OAuth failed: {exc}"
                    )
            else:
                self.app.call_from_thread(
                    status.update, "OAuth failed: state mismatch"
                )

        Thread(target=_flow, daemon=True).start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "codex-oauth-btn":
            self._run_codex_oauth()
            return
        # ... existing button handling ...
```

Modify `setup.py` `_save_credentials()` to handle codex tokens (after backends loop):

```python
        # Codex OAuth tokens (stored by OAuth flow, not by text fields)
        if hasattr(self, "_codex_tokens"):
            tokens = self._codex_tokens
            store.set("codex", "access_token", tokens.access_token)
            store.set("codex", "refresh_token", tokens.refresh_token)
            store.set("codex", "expires", str(tokens.expires))
            store.set("codex", "account_id", tokens.account_id)
```

**Step 2: Verify the TUI loads without errors**

Run: `uv run python -c "from corvus.cli.screens.backends import BACKENDS; print([b[0] for b in BACKENDS])"`
Expected: `['claude', 'openai', 'codex', 'ollama', 'kimi', 'openai-compat']`

**Step 3: Commit**

```bash
git add corvus/cli/screens/backends.py corvus/cli/setup.py
git commit -m "feat: add Codex ChatGPT OAuth to setup wizard"
```

---

### Task 7: Run Full Test Suite and Final Verification

**Files:**
- No new files

**Step 1: Run all unit tests**

Run: `uv run python -m pytest tests/unit/ -v --timeout=30`
Expected: All passing (including new oauth + credential store tests)

**Step 2: Run lint**

Run: `uv run ruff check corvus/auth/ corvus/credential_store.py corvus/cli/screens/backends.py corvus/cli/setup.py tests/unit/test_openai_oauth.py tests/unit/test_credential_store_codex.py`
Expected: No errors

**Step 3: Verify spawn env still passes CODEX_API_KEY**

Run: `uv run python -m pytest tests/unit/test_acp_sandbox.py -v`
Expected: All passing (existing tests already cover CODEX_API_KEY passthrough)

**Step 4: Commit any lint fixes if needed**

```bash
git add -u
git commit -m "fix: resolve lint issues in OAuth integration"
```
