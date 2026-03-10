---
title: "LiteLLM Proxy Integration Design"
type: spec
status: implemented
date: 2026-03-06
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# LiteLLM Proxy Integration Design

**Date:** 2026-03-06
**Status:** Approved
**Goal:** Replace hand-rolled model routing (client_pool, ollama_probe, env-swap) with LiteLLM proxy, keeping claude-agent-sdk orchestration and KimiProxy intact.

---

## Motivation

Corvus currently manages multi-backend model routing via ~370 lines of custom code across `client_pool.py`, `ollama_probe.py`, and parts of `model_router.py`. This works but:

1. **Fallback/retry logic is basic** — single linear fallback chain, no cooldowns, no error-specific retry policies
2. **Adding providers requires custom code** — each backend needs probe logic, env-swap wiring, format translation
3. **No cost tracking** — token counts exist but no spend tracking or budget controls
4. **Reinventing the wheel** — LiteLLM solves all of this with 38k GitHub stars of battle-testing

## Architecture

### Current Flow

```
claude-agent-sdk → ANTHROPIC_BASE_URL (env-swapped per call) → Anthropic / Ollama / KimiProxy
                   ↑ client_pool.build_env() swaps per backend
                   ↑ ollama_probe resolves URLs
                   ↑ model_router manages fallback chain
```

### New Flow

```
claude-agent-sdk → ANTHROPIC_BASE_URL=http://127.0.0.1:4000 → LiteLLM Proxy → Anthropic
                                                                             → Ollama
                                                                             → OpenAI
                                                                             → Groq / Bedrock / etc.
                                                                             → KimiProxy (localhost:8100)

config/models.yaml (source of truth) → LiteLLMManager.generate_config() → litellm_config.yaml
```

The SDK always talks to `localhost:4000`. LiteLLM handles backend selection, fallbacks, retries, cooldowns, cost tracking, and provider API translation. KimiProxy stays as a separate process — registered as a custom backend in LiteLLM config.

## What Gets Replaced

| File | Lines | Action |
|------|-------|--------|
| `corvus/client_pool.py` | 133 | **Deleted** — LiteLLM handles backend resolution, env swaps, fallbacks |
| `corvus/ollama_probe.py` | 88 | **Deleted** — LiteLLM probes Ollama natively |
| `corvus/model_router.py` discovery | ~100 | **Simplified** — `discover_models()` queries LiteLLM `/models` endpoint |
| `corvus/gateway/options.py` env-swap | ~30 | **Simplified** — no more `build_env()` calls, `ANTHROPIC_BASE_URL` is always `localhost:4000` |

## What Stays Unchanged

- `claude-agent-sdk` orchestration (tools, multi-turn, agents, streaming)
- `corvus/gateway/options.py` — still builds `ClaudeAgentOptions` (tool policies, hooks, confirm gate)
- `corvus/kimi_proxy.py` — stays as-is, registered as LiteLLM backend
- `config/models.yaml` — stays as source of truth for agent-to-model mapping
- `CapabilitiesRegistry`, `ConfirmQueue`, permissions — all untouched
- All security layers — deny-wins-over-allow, sandbox-by-default

## New Components

### `corvus/litellm_manager.py` (~150 lines)

Manages LiteLLM proxy lifecycle as an embedded subprocess.

```python
class LiteLLMManager:
    """Start/stop LiteLLM proxy, generate config from models.yaml."""

    def __init__(self, port: int = 4000, host: str = "127.0.0.1") -> None:
        self._port = port
        self._host = host
        self._process: subprocess.Popen | None = None

    async def start(self, models_yaml: Path) -> None:
        """Generate config, start proxy, wait for health check."""
        config_path = self.generate_config(models_yaml)
        self._process = subprocess.Popen(
            ["litellm", "--config", str(config_path),
             "--host", self._host, "--port", str(self._port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        await self._wait_healthy()
        os.environ["ANTHROPIC_BASE_URL"] = f"http://{self._host}:{self._port}"

    async def stop(self) -> None:
        """Graceful shutdown."""
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=10)

    def generate_config(self, models_yaml: Path) -> Path:
        """Translate config/models.yaml → litellm_config.yaml."""
        # Read our models.yaml, emit LiteLLM format
        ...
```

### Config Translation

`config/models.yaml` (our source of truth) generates `litellm_config.yaml` at startup:

```yaml
# Generated from config/models.yaml
model_list:
  - model_name: "sonnet"
    litellm_params:
      model: "anthropic/claude-sonnet-4-20250514"
      api_key: "os.environ/ANTHROPIC_API_KEY"
  - model_name: "opus"
    litellm_params:
      model: "anthropic/claude-opus-4-20250514"
      api_key: "os.environ/ANTHROPIC_API_KEY"
  - model_name: "haiku"
    litellm_params:
      model: "anthropic/claude-haiku-4-5-20251001"
      api_key: "os.environ/ANTHROPIC_API_KEY"
  - model_name: "ollama/llama3"
    litellm_params:
      model: "ollama/llama3"
      api_base: "http://localhost:11434"
  - model_name: "kimi-k2"
    litellm_params:
      model: "anthropic/kimi-k2"
      api_base: "http://localhost:8100"
      api_key: "not-needed"

router_settings:
  routing_strategy: "simple-shuffle"
  num_retries: 3
  allowed_fails: 3
  cooldown_time: 30
  retry_after: 5
  fallbacks:
    - sonnet: ["ollama/llama3"]
    - opus: ["sonnet", "ollama/llama3"]
    - haiku: ["ollama/llama3"]
```

### Runtime Wiring

In `corvus/gateway/runtime.py` lifespan:

```python
async def lifespan(app):
    litellm_mgr = LiteLLMManager()
    await litellm_mgr.start(Path("config/models.yaml"))
    # ... build runtime (ModelRouter, agents, etc.) ...
    yield
    await litellm_mgr.stop()
```

### ModelRouter Simplification

`model_router.py` keeps agent-to-model mapping but discovery changes:

```python
# Before: probe each backend manually
def discover_models(self):
    if os.environ.get("ANTHROPIC_API_KEY"):
        self._models.extend(claude_models)
    resolved = resolve_ollama_url(urls)
    if resolved:
        self._models.extend(probe_ollama_models(resolved))

# After: query LiteLLM
def discover_models(self):
    resp = httpx.get("http://127.0.0.1:4000/models")
    for model in resp.json()["data"]:
        self._models.append(ModelInfo(...))
```

### options.py Simplification

```python
# Before: per-call env-swap
backend_env = runtime.client_pool.build_env(backend_name)
opts = ClaudeAgentOptions(env={**backend_env, ...})

# After: env already set globally, no per-call swap
opts = ClaudeAgentOptions(env={...})  # ANTHROPIC_BASE_URL already points to LiteLLM
```

## Security

- **Local-only binding** — LiteLLM proxy binds to `127.0.0.1:4000`, no network exposure
- **API keys in env vars only** — LiteLLM reads from `os.environ` (injected by `credential_store.py`), never written to generated config files on disk
- **No multi-tenant features** — single-user, no LiteLLM auth/team/budget features enabled
- **Tool policies unchanged** — `CapabilitiesRegistry`, `ConfirmQueue`, deny-wins-over-allow all stay exactly as they are
- **KimiProxy isolation** — separate process, LiteLLM just forwards to it
- **Subprocess containment** — LiteLLM runs as a child process, terminated on gateway shutdown

## Config-Driven Philosophy

Everything stays config-driven and live-reloadable:

- `config/models.yaml` remains the single source of truth
- `litellm_config.yaml` is regenerated on startup (never hand-edited)
- Adding a new provider = add backend entry to `models.yaml`, restart
- Fallback chains, retry policies, cooldown times all configurable in `models.yaml`
- No hardcoded model names, URLs, or provider logic in Python code

## Dependencies

- `litellm` Python package (MIT license, actively maintained)
- Installed via `uv pip install litellm`
- Adds ~50 transitive dependencies (acceptable trade-off for replacing 370 lines of custom routing code)

## Testing Strategy

- **Config translation tests** — verify `models.yaml` → `litellm_config.yaml` produces correct output
- **Health check tests** — verify `LiteLLMManager` startup/shutdown lifecycle
- **Model discovery tests** — verify `discover_models()` correctly queries LiteLLM `/models`
- **Fallback tests** — verify fallback chain behavior (may require integration test with real LiteLLM)
- **Regression** — full test suite must pass after routing code removal
