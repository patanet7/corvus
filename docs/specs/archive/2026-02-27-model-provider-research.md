---
title: "Model Provider Research: Kimi, Ollama, and Multi-Model Routing"
type: spec
status: implemented
date: 2026-02-27
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Model Provider Research — Kimi, Ollama, and Multi-Model Routing

> **Date**: 2026-02-27 (updated 2026-02-28)
> **Status**: Bridge connection VERIFIED, implementation pending

## Summary

Researched how the third-party OpenClaw gateway, PicoClaw, and the Claude Agent SDK handle model routing and non-Claude model providers. Key findings:

1. **Kimi bridge (ACP mode)** authenticates via `X-Kimi-Bot-Token` HTTP header — WebSocket connection confirmed working
2. **Kimi coding API** (`api.kimi.com/coding/`) speaks Anthropic Messages format natively — drop-in for the SDK
3. **The SDK supports per-session env overrides** via `ClaudeAgentOptions.env` — can route different sessions to different backends
4. **Ollama v0.14+** also speaks Anthropic Messages format natively

---

## Architecture Comparison

| | **OpenClaw (third-party, Node.js)** | **Claude Agent SDK (us)** | **PicoClaw (Go)** |
|---|---|---|---|
| **Model calls** | Direct REST API with provider abstraction | SDK subprocess (Claude Code CLI) | Direct REST API |
| **API format** | Provider-specific (adapters per format) | Anthropic Messages only | OpenAI-compatible |
| **Multi-model** | 15+ providers native | Claude tiers + `ANTHROPIC_BASE_URL` swap | `vendor/model` config |
| **Agent routing** | Deterministic bindings (channel/peer) | LLM-based (description matching) | Command-prefix parsing |
| **Agent loop** | Gateway owns ReAct loop | SDK subprocess owns it | Gateway owns it |

---

## Kimi Integration — Three Components

### 1. Kimi Bot Bridge (Channel via kimi-claw)

The kimi-claw plugin connects to Kimi's WebSocket bridge and forwards frames to/from the local gateway.

**Two modes** (from `~/.openclaw/extensions/kimi-claw/dist/src/`):

#### ACP Mode (Default — VERIFIED WORKING)

Uses `JsonRpcWsClient` (`jsonrpc-ws-client.js`):
- Auth via **`X-Kimi-Bot-Token`** HTTP header at WebSocket upgrade
- No post-connection handshake needed — ready immediately on open
- JSON-RPC protocol for message passing
- Handles text heartbeats ("ping"/"pong") and JSON `{"type": "ping"}`
- Reconnect notification via `{"jsonrpc": "2.0", "method": "_kimi.com/reconnect"}`
- On HTTP 401 or WebSocket close code 4001: marks auth failed, stops retrying

```
Headers sent at WebSocket upgrade:
  X-Kimi-Claw-Version: 0.7.4
  X-Kimi-Bot-Token: <KIMI_BOT_TOKEN>
```

#### Bridge Mode (Legacy)

Uses `HandshakeWsClient` (`ws-client.js`):
- Only `X-Kimi-Claw-Version` header at HTTP level
- Auth via JSON connect handshake frame after WebSocket opens
- Device identity (`buildDeviceAuthField`) used only for gateway connection, not bridge
- Challenge-response protocol with nonce

**Architecture:**
```
┌─────────────┐     WebSocket      ┌──────────────┐     WebSocket     ┌──────────────┐
│  Kimi App   │ ←────────────────→ │  kimi-claw   │ ←───────────────→ │ Corvus Gateway│
│ (kimi.com)  │  X-Kimi-Bot-Token  │  (sidecar)   │  device auth      │  (FastAPI)   │
└─────────────┘  ACP mode          └──────────────┘  /ws endpoint     └──────────────┘
                                    frame forwarder                    ClaudeSDKClient
                                    Node.js                            → Claude API
```

**Auth**: `KIMI_BOT_TOKEN` — this IS the credential. Not an API key.

**Default config** (from `config.js`):
| Setting | Default |
|---|---|
| Bridge URL | `wss://www.kimi.com/api-claw/bots/agent-ws` |
| Gateway URL | `ws://127.0.0.1:18789` |
| Protocol | 3 |
| Bridge Mode | `acp` |
| Prompt Timeout | 30 minutes |
| Default Model | `kimi-coding` / `k2p5` |

### 2. Kimi Coding API (Model Provider)

- **Endpoint**: `https://api.kimi.com/coding/`
- **API format**: `anthropic-messages` (Anthropic Messages API compatible!)
- **Model**: `k2p5` (Kimi K2.5)
- **Auth**: `KIMI_API_KEY` env var (separate from bot token)
- **Context window**: 262,144 tokens
- **Max output**: 32,768 tokens
- **Cost**: Free (all zeros in third-party OpenClaw config)
- **Source**: `openclaw-src/src/agents/models-config.providers.ts` (third-party reference)

Since it speaks Anthropic Messages format, the SDK can talk to it via env var swap:
```python
ClaudeAgentOptions(env={
    "ANTHROPIC_BASE_URL": "https://api.kimi.com/coding/",
    "ANTHROPIC_API_KEY": os.environ["KIMI_API_KEY"],
    "ANTHROPIC_MODEL": "k2p5",
})
```

### 3. Moonshot REST API (Legacy/Alternative)

- **Endpoint**: `https://api.moonshot.ai/v1` (or `api.moonshot.cn/v1`)
- **API format**: OpenAI chat completions (NOT Anthropic format)
- **Auth**: `MOONSHOT_API_KEY` (separate credential)
- NOT directly compatible with Claude Agent SDK

---

## Credentials Inventory

| Credential | Purpose | Format | We Have It? |
|---|---|---|---|
| `KIMI_BOT_TOKEN` | kimi-claw bridge (WebSocket channel) | `sk-CDYWRI...` | **YES** (regenerated 2026-02-28) |
| `KIMI_API_KEY` | Kimi coding API (Anthropic Messages) | Unknown | **NO — need from kimi.com settings** |
| `MOONSHOT_API_KEY` | Moonshot REST API (OpenAI format) | Unknown | **NO** |
| `ANTHROPIC_API_KEY` | Claude API / Claude Code CLI | `sk-ant-oat01-...` | **YES** |

---

## SDK Env Var Reference for Model Routing

| Variable | Purpose |
|---|---|
| `ANTHROPIC_BASE_URL` | Custom API endpoint (replaces api.anthropic.com) |
| `ANTHROPIC_API_KEY` | API key (sent as `x-api-key` header) |
| `ANTHROPIC_AUTH_TOKEN` | Bearer token (sent as `Authorization: Bearer`) |
| `ANTHROPIC_MODEL` | Override primary model name |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Override haiku tier model |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Override sonnet tier model |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Override opus tier model |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Override model for subagents |

The `env` field on `ClaudeAgentOptions` is merged into the subprocess environment. Each `ClaudeSDKClient` instance gets its own subprocess.

---

## How to Use Ollama

Ollama v0.14.0+ natively supports the Anthropic Messages API:

```python
ClaudeAgentOptions(env={
    "ANTHROPIC_BASE_URL": "http://localhost:11434",
    "ANTHROPIC_AUTH_TOKEN": "ollama",
    "ANTHROPIC_API_KEY": "",
})
```

Ollama runs on laptop-server (GPU). From Docker: `http://host.docker.internal:11434` or host IP.

---

## Verified Test Results

| Test | Endpoint | Auth | Result |
|---|---|---|---|
| **Kimi bridge (ACP mode)** | `wss://www.kimi.com/api-claw/bots/agent-ws` | `X-Kimi-Bot-Token` header | **SUCCESS** — WebSocket connected, stable |
| Kimi bridge (Bearer header) | same | `Authorization: Bearer` | **401** (wrong header) |
| Kimi bridge (frame-only auth) | same | `X-Kimi-Claw-Version` only | **401** (missing auth header) |
| Kimi bridge (no headers) | same | none | **401** (missing auth header) |
| Direct API → Moonshot | `api.moonshot.ai/v1/chat/completions` | KIMI_BOT_TOKEN | **401** (wrong credential type) |
| Direct API → Kimi Coding | `api.kimi.com/coding/v1/messages` | KIMI_BOT_TOKEN | **401** (wrong credential type) |
| SDK install on laptop-server | `uv pip install claude-agent-sdk` | N/A | **SUCCESS** |
| uv install on laptop-server | `curl install.sh` | N/A | **SUCCESS** (v0.10.7) |

**401 response body**: `"missing authorization header or ticket"` — server explicitly requires `X-Kimi-Bot-Token` or ticket param.

---

## Kimi-Claw Source Code Analysis

### Key Discovery: Two Client Classes

| Class | File | Used By | Auth Mechanism |
|---|---|---|---|
| `JsonRpcWsClient` | `jsonrpc-ws-client.js` | **ACP mode** (default) | `X-Kimi-Bot-Token` HTTP header |
| `HandshakeWsClient` | `ws-client.js` | Bridge mode (legacy) | JSON connect frame after open |

The `KIMI_BOT_TOKEN_HEADER = "X-Kimi-Bot-Token"` constant in `JsonRpcWsClient` is the auth mechanism for ACP mode. The token is set directly as an HTTP header during the WebSocket upgrade:

```javascript
const n = {...this.headers};
this.token && (n["X-Kimi-Bot-Token"] = this.token);
this.ws = new WebSocket(this.url, {headers: n});
```

### Device Identity (Ed25519 keypair)

`utils/device-identity.js` manages an Ed25519 keypair at `~/.openclaw/plugins/kimi-claw/device.json`:
- **Purpose**: Signs auth payloads for the **gateway** connection (NOT the bridge)
- `buildDeviceAuthField()` creates a signed device attestation with: deviceId, publicKey, signature, signedAt, nonce
- Format: `version|deviceId|clientId|clientMode|role|scopes|signedAtMs|token[|nonce]` → Ed25519 signature
- The bridge (Kimi-side) does NOT use device auth — only the gateway-side connection does

### ACP Gateway Bridge

`acp-gateway-bridge.js` + `acp-gateway/bridge-core.js`:
- Full ACP protocol handler with session management, tool dispatch, prompt conversion
- Handles: `acp.prompt.start`, `acp.prompt.feedback`, terminal/shell sessions
- Tool results dispatched via strategies in `tool-result-payload-strategies.js`
- Session history replay, file resolution, prompt timeout management

---

## Architecture: How Kimi Bridge Fits Our Gateway

### Option A: Write Python Kimi Bridge (Recommended)

Replace the Node.js kimi-claw plugin with a Python WebSocket client:
1. Connect to `wss://www.kimi.com/api-claw/bots/agent-ws` with `X-Kimi-Bot-Token` header
2. Receive ACP/JSON-RPC frames from Kimi
3. Translate to our gateway's protocol and dispatch to `ClaudeSDKClient`
4. Send responses back through the bridge

### Option B: Run kimi-claw as Sidecar

Run the actual kimi-claw Node.js plugin as a Docker sidecar:
- PRO: Exact protocol compatibility, maintained by Kimi team
- CON: Requires Node.js container, talks to OpenClaw gateway protocol (not ours)
- Would need the third-party OpenClaw gateway running too — defeats purpose

### Option C: Hybrid

Use kimi-claw for bridge auth/connection, write a thin protocol translator in Python.

---

## Action Items

1. ~~**Test bridge WebSocket**: Connect with bot token~~ **DONE** — ACP mode works with `X-Kimi-Bot-Token`
2. **Get KIMI_API_KEY**: From kimi.com settings → add to `~/.secrets/claw.env`
3. **Test Kimi coding API**: `ANTHROPIC_BASE_URL=https://api.kimi.com/coding/` with real key
4. **Test Ollama**: Install on laptop-server, test with SDK env swap
5. **Wire ModelRouter**: Connect `model_router.py` → `build_options()` in server.py
6. **Build Python Kimi bridge**: WebSocket client that speaks ACP protocol, translates to our gateway

---

## Third-Party OpenClaw Source References (on laptop-server at ~/openclaw-src/)

### Model Providers (`src/agents/`)
- `models-config.providers.ts` — All provider definitions (Kimi, Ollama, Qwen, Doubao, etc.)
- `models-config.providers.kimi-coding.test.ts` — Kimi provider tests
- `model-auth.ts` — API key resolution (`KIMI_API_KEY`, `KIMICODE_API_KEY`)
- `ollama-stream.ts` — Ollama streaming
- `context.ts` — Agent context + model selection

### Kimi Bridge (`~/.openclaw/extensions/kimi-claw/dist/src/`)
- `service.js` — Main service orchestrator (selects ACP vs bridge mode)
- `service/mode-acp.js` — ACP mode: `JsonRpcWsClient` for bridge, `HandshakeWsClient` for gateway
- `service/mode-bridge.js` — Legacy bridge mode: dual `HandshakeWsClient`
- `jsonrpc-ws-client.js` — ACP bridge client with `X-Kimi-Bot-Token` auth
- `ws-client.js` — Handshake-based WebSocket client (legacy bridge + gateway)
- `config.js` — Default URLs, timeouts, protocol version
- `utils/device-identity.js` — Ed25519 keypair for gateway device auth
- `acp-gateway-bridge.js` — Full ACP protocol handler
- `acp-gateway/bridge-core.js` — Core ACP session/prompt management
