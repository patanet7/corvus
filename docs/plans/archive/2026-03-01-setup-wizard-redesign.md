# Setup Wizard Redesign — Multi-Backend Model Configuration

**Date:** 2026-03-01
**Status:** Approved
**Scope:** Replace single-provider Anthropic setup with multi-backend model configuration + graceful degradation

## Problem

The current setup wizard (`mise run setup`) is hardcoded to Anthropic:
- Only accepts `sk-ant-` API keys
- No skip option on the API key screen
- No support for local models (Ollama), OpenAI, Kimi, or generic OpenAI-compatible endpoints
- Server crashes on first run if `DATA_DIR` directories don't exist (fixed separately)
- No graceful degradation — server assumes an LLM is always available

## Design

### Wizard Flow

```
Welcome → Model Backends → Services → Passphrase → Complete
```

The `AnthropicScreen` is replaced by `ModelBackendsScreen`. All other screens remain unchanged. Every screen has Skip/Skip All — the entire wizard can be skipped.

### ModelBackendsScreen

Five toggleable backend sections, all **off by default**. When toggled on, input fields appear below. When off, fields are hidden.

| Backend | Toggle label | Fields when enabled | Defaults |
|---------|-------------|---------------------|----------|
| Claude | Anthropic Claude | Auth method selector: Setup Token (OAuth via `claude-agent-sdk`) **or** API key (password, `sk-ant-` validation) | — |
| OpenAI | OpenAI | API key (password, `sk-` prefix check) | — |
| Ollama | Ollama (local) | Base URL | `http://localhost:11434` |
| Kimi | Kimi / Moonshot | API key (password) | — |
| OpenAI-compatible | OpenAI-compatible endpoint | Label/name, Base URL, API key (optional, password) | — |

**Claude auth methods:**
- **Setup Token** (recommended): Uses the Claude Code OAuth flow via `claude-agent-sdk`. Opens browser for auth, receives token automatically. Same flow as `openclaw models auth setup-token`. No manual key entry needed.
- **API Key**: Manual paste of `sk-ant-...` key for users who prefer direct API access.

**Validation rules (format-only, no network probes):**
- Claude (API key mode): `sk-ant-` prefix + 80+ chars
- Claude (setup token mode): handled by OAuth flow
- OpenAI: `sk-` prefix + non-empty
- Ollama: valid URL format
- Kimi: non-empty
- OpenAI-compat: valid URL format, key optional

**Buttons:**
- "Skip All →" — proceeds with no backends configured
- "← Back" — returns to Welcome
- "Next →" — saves enabled backends, proceeds to Services

### Credential Storage

All values saved to `~/.corvus/credentials.json` via existing SOPS credential store:

```
claude/api_key
openai/api_key
ollama/base_url
kimi/api_key
openai_compat/label
openai_compat/base_url
openai_compat/api_key
```

### Server-Side Graceful Degradation

On `mise run serve`:

1. `_ensure_dirs()` creates all required directories + init SQLite schema (already done)
2. Backend discovery — read credential store, determine which backends are active
3. Ollama probe — if Ollama configured, call `GET {base_url}/api/tags` at startup, log discovered models
4. Health endpoint (`/health`) reports backend status:
   ```json
   {
     "status": "degraded",
     "backends": {
       "claude": {"status": "configured"},
       "ollama": {"status": "configured", "models": ["llama3.3", "phi-3"]},
       "openai": {"status": "not_configured"},
       "kimi": {"status": "not_configured"}
     }
   }
   ```
5. Chat with no LLM backend returns:
   ```json
   {"error": "no_llm_configured", "message": "No LLM backend configured. Run 'mise run setup' to add one."}
   ```

### models.yaml Integration

The wizard writes credentials only. `models.yaml` defines what's *possible*; the credential store determines what's *active*. No changes to `models.yaml` format needed.

At startup, ModelRouter checks credential store to build the active backend list. Per-agent model assignment stays in `models.yaml` — users edit directly (and eventually via a frontend model selector).

Updated backends section (documentation only, structure unchanged):

```yaml
backends:
  claude:
    type: sdk_native
    # Active when claude/api_key in credential store
  openai:
    type: openai
    # Active when openai/api_key in credential store
  kimi:
    type: proxy
    base_url: "http://localhost:8100"
    # Active when kimi/api_key in credential store
  ollama:
    type: env_swap
    # Active when ollama/base_url in credential store
    # base_url from credential store, not hardcoded
  openai_compat:
    type: openai
    # Active when openai_compat/base_url in credential store
```

### CompleteScreen Updates

Summary screen updated to show all 5 backends:

```
  Claude (Anthropic)     configured
  OpenAI                 skipped
  Ollama (local)         configured
  Kimi                   skipped
  OpenAI-compatible      skipped
  Home Assistant         configured
  Paperless              skipped
  Firefly III            skipped
  Obsidian               skipped
  Break-glass passphrase set
```

### WelcomeScreen Updates

- Update copy: "Corvus" → "Corvus" branding
- Navigate to `"backends"` instead of `"anthropic"`

## Patterns from OpenClaw

Adopted:
- `provider/model` naming convention for future model references
- Auto-discovery for local models (Ollama) at server startup, not in wizard
- Store connection details only; no plaintext secrets in config files
- Graceful degradation with clear health reporting

Deferred (future work):
- In-chat `/model` switching (frontend model selector)
- Ordered fallback chains with rate-limit rotation
- Hot-reload of models.yaml
- `doctor --fix` self-healing config validation

## Files Changed

| File | Change |
|------|--------|
| `corvus/cli/screens/anthropic.py` | Delete (replaced by backends) |
| `corvus/cli/screens/backends.py` | New — ModelBackendsScreen with 5 toggleable backends |
| `corvus/cli/screens/welcome.py` | Navigate to `"backends"`, update branding |
| `corvus/cli/screens/complete.py` | Show all 5 backends in summary |
| `corvus/cli/setup.py` | Register `"backends"` screen, remove `"anthropic"` |
| `corvus/server.py` | Backend discovery + Ollama probe at startup, graceful chat error |
| `corvus/model_router.py` | Check credential store for active backends |
| `config/models.yaml` | Add `openai` + `openai_compat` backend entries |

## Out of Scope

- Per-agent model assignment in the wizard (stays in models.yaml)
- OpenAI provider adapter (routing layer — separate task, key stored now)
- Frontend model selector UI
- API key rotation / multi-key support
- Hot-reload of config changes
