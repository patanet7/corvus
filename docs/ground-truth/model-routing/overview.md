---
subsystem: model-routing
last_verified: 2026-03-10
---

# Model Routing — LiteLLM Proxy Architecture

Corvus routes all model traffic through a LiteLLM proxy running as an embedded subprocess on `127.0.0.1:4000`. `LiteLLMManager` generates `litellm_config.yaml` from `config/models.yaml` at startup and sets `ANTHROPIC_BASE_URL` so the `claude-agent-sdk` sends all requests through the proxy. `ModelRouter` reads `config/models.yaml` for per-agent and per-skill model assignments. The former `client_pool.py` (env-swap routing) has been deleted; `ollama_probe.py` remains only for the cognee memory backend.

## Ground Truths

- `LiteLLMManager` lives in `corvus/litellm_manager.py` and is a field on `GatewayRuntime`.
- At startup, `server.py` lifespan calls `litellm_manager.start(Path("config/models.yaml"))` before `model_router.discover_models()`.
- If the LiteLLM proxy fails to start, the gateway logs a warning and falls back to config-based model discovery.
- `generate_litellm_config()` translates `config/models.yaml` into a LiteLLM config dict with `model_list` and `router_settings`.
- SDK-native models (haiku, sonnet, opus) are registered with `anthropic/` prefix; full Claude Code model IDs (e.g. `claude-sonnet-4-20250514`) are also registered.
- Ollama backends (type `env_swap`) produce an `ollama/*` wildcard entry with the configured `api_base`.
- Kimi backend (type `proxy`) routes through KimiProxy at `http://localhost:8100` as an `openai/kimi-k2` model.
- OpenAI and OpenAI-compatible backends are added when present in the `backends:` section.
- API keys are referenced as `os.environ/VAR_NAME` in generated config, never inlined. `_anthropic_api_key_ref()` resolves the correct env var at config generation time: prefers `CLAUDE_CODE_OAUTH_TOKEN` (OAuth setup tokens), falls back to `ANTHROPIC_API_KEY`.
- Router settings (retries, cooldown, strategy) are read from the `litellm:` section of `models.yaml` with hardcoded defaults (3 retries, 30s cooldown, simple-shuffle).
- Fallback chains auto-generate: each SDK-native model falls back to `ollama/*` when an Ollama backend is configured.
- The proxy binds to `127.0.0.1` only; no network exposure.
- Shutdown sends SIGTERM with a 10s timeout, then SIGKILL.
- `ModelRouter.discover_models()` queries `GET /models` on the LiteLLM proxy; on failure, populates from `_sdk_native_models` in config.
- Model resolution priority: skill override > agent override > default model (`sonnet`).
- Complexity-based routing maps high/medium/low to opus/sonnet/haiku.
- `resolve_best_available()` provides tier-ordered fallback: opus > sonnet > haiku > first available.

## Boundaries

- **Depends on:** `config/models.yaml`, `litellm` Python package, `httpx`, `pyyaml`
- **Consumed by:** `GatewayRuntime`, `server.py` lifespan, `chat_session.py`, `options.py`
- **Does NOT:** handle tool policies, agent orchestration, KimiProxy lifecycle, or Ollama URL probing for memory backends
