---
title: "ACP Auth Integration Design"
type: spec
status: implemented
date: 2026-03-06
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# ACP Auth Integration Design

## Goal

Store Codex (OpenAI) OAuth tokens in Corvus's SOPS credential store and inject them at ACP agent spawn time — same pattern as every other credential in the system.

## Architecture

Corvus runs the OpenAI PKCE OAuth flow itself (not Codex), stores `{access_token, refresh_token, expires, account_id}` in the SOPS credential store under the `"codex"` service key, handles token refresh at runtime, and injects the access token as `CODEX_API_KEY` into the ACP spawn environment. Modeled after OpenClaw's approach.

## Components

### 1. OAuth Flow Module — `corvus/auth/openai_oauth.py`

Runs PKCE OAuth against OpenAI's auth endpoint:

1. Generate PKCE `code_verifier` + `code_challenge` (S256) + random `state`
2. Start local HTTP callback server on `127.0.0.1:1455`
3. Open browser to `https://auth.openai.com/oauth/authorize` with PKCE params
4. Wait for callback with authorization code
5. Exchange code at `https://auth.openai.com/oauth/token` for tokens
6. Decode access token JWT to extract `account_id`
7. Return `CodexOAuthResult(access_token, refresh_token, expires, account_id)`

Also provides `refresh_access_token(refresh_token) -> CodexOAuthResult` for runtime refresh.

**No external deps** — uses stdlib only (`http.server`, `urllib.request`, `hashlib`, `secrets`, `json`, `webbrowser`, `base64`).

### 2. Credential Store Integration

Stored under `"codex"` service in SOPS credential store (`~/.corvus/credentials.json`):

```json
{
  "codex": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "expires": "1736160000000",
    "account_id": "acc_123"
  }
}
```

`CredentialStore.inject()` gets a new `codex` block that:
- Checks if `expires` < current time
- If expired, calls `refresh_access_token()` and updates the store with new tokens
- Sets `os.environ["CODEX_API_KEY"]` to the (fresh) access token

### 3. Setup Wizard Integration

Add `"codex"` backend to the backends screen in the setup TUI. Instead of a text input, the Codex toggle shows a "Sign in with ChatGPT" button that triggers the OAuth flow. On success, tokens are written to the credential store.

The setup wizard maps:
- `backend_id = "codex"` → runs OAuth flow → stores result under `"codex"` service

### 4. Spawn-Time Injection (no changes needed)

The existing pipeline already handles this:

1. `credential_store.inject()` → sets `os.environ["CODEX_API_KEY"]`
2. `build_acp_spawn_env()` → passes through `CODEX_API_KEY` (already in `_SPAWN_PASSTHROUGH_KEYS`)
3. Codex ACP process reads `CODEX_API_KEY` from env → authenticates

### 5. CLI Auth Command

Add `corvus auth login --provider codex` as a standalone command (mirrors OpenClaw's `openclaw models auth login --provider openai-codex`). This runs the same OAuth flow outside the TUI wizard, for users who want to add/refresh Codex auth after initial setup.

## Data Flow

```
Setup/CLI → OAuth flow → {access, refresh, expires, account_id}
                              ↓
                    SOPS credential store ("codex" service)
                              ↓
              inject() → refresh if expired → os.environ["CODEX_API_KEY"]
                              ↓
              build_acp_spawn_env() → passes through CODEX_API_KEY
                              ↓
                    Codex ACP process reads env → authenticated
```

## Testing

- **OAuth flow**: Behavioral test with a fake local HTTP server simulating OpenAI's token endpoint. Test PKCE generation, code exchange, JWT decode, refresh flow.
- **Credential store**: Test `codex` service round-trip — set tokens, verify inject() sets env var, verify refresh is called when expired.
- **Spawn env**: Already covered — `CODEX_API_KEY` passthrough is tested in `test_acp_sandbox.py`.
