# Corvus Model Routing Strategy

> Per-agent model assignment, fallback chains, and cost optimization.

## Overview

Corvus supports **per-agent model overrides** — each domain agent can run on a different LLM backend. This enables cost optimization (cheap models for simple agents), capability matching (stronger models for high-stakes reasoning), and local inference for privacy-sensitive tasks.

Models are configured in `~/.openclaw/openclaw.json` using the `provider/model` format (e.g., `anthropic/claude-sonnet-4-6`).

---

## Configuration

### Global default

All agents inherit from `agents.defaults.model` unless they override it:

```json5
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-sonnet-4-6",
        "fallbacks": ["openai/gpt-4o"]
      },
      "models": {
        // Allowlist — only these models can be used
        "anthropic/claude-opus-4-6":   { "alias": "Opus" },
        "anthropic/claude-sonnet-4-6": { "alias": "Sonnet" },
        "anthropic/claude-haiku-4-5":  { "alias": "Haiku" },
        "openai/gpt-4o":              { "alias": "GPT-4o" },
        "google/gemini-2.5-pro":      { "alias": "Gemini" },
        "moonshot/kimi-k2":           { "alias": "Kimi K2" },
        "moonshot/kimi-k2.5":         { "alias": "Kimi K2.5" },
        "ollama/phi-3-mini":          { "alias": "Phi-3 (local)" }
      }
    }
  }
}
```

### Per-agent override

Each agent in `agents.list` can specify its own model — string form (primary only) or object form (primary + fallbacks):

```json5
{
  "agents": {
    "list": [
      {
        "id": "router",
        "model": "anthropic/claude-haiku-4-5",
        // Fast, cheap — intent classification only
      },
      {
        "id": "finance",
        "model": {
          "primary": "anthropic/claude-opus-4-6",
          "fallbacks": ["anthropic/claude-sonnet-4-6"]
        },
        "params": { "temperature": 0.2 }
        // Strong reasoning, low temp for precision
      },
      {
        "id": "homelab",
        "model": "moonshot/kimi-k2",
        // Kimi K2 — good tool use, low cost for infra ops
      },
      {
        "id": "music",
        "model": "moonshot/kimi-k2",
        // Kimi K2 — memory-only, low complexity
      }
    ]
  }
}
```

### Override rules

| Format | Behavior |
|--------|----------|
| `"model": "provider/model"` | Replaces primary only; inherits default fallbacks |
| `"model": { "primary": "...", "fallbacks": [...] }` | Replaces both primary and fallbacks |
| `"model": { "primary": "...", "fallbacks": [] }` | Replaces primary, **disables** fallbacks |
| *(omitted)* | Inherits `agents.defaults.model` entirely |

### Per-agent parameters

`agents.list[].params` merges on top of the model's default parameters:

```json5
{
  "id": "homelab",
  "model": "anthropic/claude-sonnet-4-6",
  "params": {
    "temperature": 0.3,       // low creativity for infra ops
    "cacheRetention": "none"  // no prompt caching (sessions are short)
  }
}
```

---

## Agent Model Assignments

> **Fill in the "Model" and "Fallback" columns below with your preferred assignments.**

| Agent | Role | Model | Fallback | Params | Rationale |
|-------|------|-------|----------|--------|-----------|
| **router** | Intent classification + dispatch | | | | Needs speed, not depth |
| **personal** | Planning, journaling, ADHD support | | | | Daily driver — balance of quality and cost |
| **work** | Meeting notes, transcripts, tasks | | | | Strong reasoning for transcript analysis |
| **finance** | Firefly III, invoices, budgets | | | | High-stakes analysis, precision |
| **homelab** | Komodo, Docker, Tailscale ops | | | | Reliable tool use, exec-heavy |
| **docs-paperless** | Document search, tagging, OCR | | | | High volume, classification-heavy |
| **inbox-email** | Gmail triage, action extraction | | | | Needs reasoning + speed for batch triage |
| **music** | Practice coaching, theory | | | | Low complexity, memory-only |

---

## Available Providers

All configured and ready to use. API keys managed via environment variables on the gateway host (never exposed to the LLM).

| Provider | Format | Key Env Var | Notes |
|----------|--------|-------------|-------|
| Anthropic | `anthropic/<model>` | `ANTHROPIC_API_KEY` | Primary. Best reasoning + tool use |
| OpenAI | `openai/<model>` | `OPENAI_API_KEY` | Strong alternative |
| Google | `google/<model>` | `GOOGLE_API_KEY` | Long context (1M+ tokens) |
| Moonshot | `moonshot/<model>` | `MOONSHOT_API_KEY` | Competitive cost, solid reasoning |
| Ollama (local) | `ollama/<model>` | *(none — local)* | Free, private, GPU-constrained |
| Groq | `groq/<model>` | `GROQ_API_KEY` | Ultra-fast inference |
| Mistral | `mistral/<model>` | `MISTRAL_API_KEY` | European provider, good multilingual |
| OpenRouter | `openrouter/<model>` | `OPENROUTER_API_KEY` | Proxy to 100+ models |

### Key rotation

Corvus rotates API keys automatically on rate-limit responses. Priority order:
1. `OPENCLAW_LIVE_<PROVIDER>_KEY` (highest)
2. `<PROVIDER>_API_KEYS` (comma-separated list)
3. `<PROVIDER>_API_KEY` (primary)
4. `<PROVIDER>_API_KEY_*` (numbered variants)

---

## Local Inference Constraints

**laptop-server** GPU: NVIDIA T1200 (4GB VRAM) — shared with Speaches (STT/TTS) and Frigate.

| Use Case | Viable Locally? | Recommended Model |
|----------|----------------|-------------------|
| Embeddings | Yes | `all-MiniLM-L6-v2` (80MB, CPU) |
| Classification / routing | Maybe | `phi-3-mini` Q4 (~2.5GB VRAM) |
| Summarization | Maybe | `phi-3-mini` Q4 |
| Primary agent reasoning | No | Quality too low at 3B scale |
| Re-ranking | Yes | `bge-reranker-base` (CPU) |

If miniserver's resources free up, larger local models (7B+) become an option there.

---

## Cost Optimization Strategy

**Tiered approach** — match model capability to task complexity:

| Tier | Model Class | Cost | Use For |
|------|------------|------|---------|
| **Tier 1** (Premium) | Opus | $$$ | Finance analysis, complex work reasoning |
| **Tier 2** (Standard) | Sonnet | $$ | Personal, homelab — when strong reasoning is critical |
| **Tier 2.5** (Value) | Kimi K2 | $ | Most agents — solid tool use + reasoning at low cost |
| **Tier 3** (Fast) | Haiku | $ | Router, classification, simple queries |
| **Tier 4** (Free) | Ollama local | Free | Embeddings, re-ranking |

---

## Implementation Checklist

- [ ] Add `agents.defaults.models` allowlist to `openclaw.json`
- [ ] Fill in agent model assignments table (above)
- [ ] Add `model` field to each agent definition in `agents.list`
- [ ] Configure fallback chains for critical agents (finance, work)
- [ ] Set per-agent `params` where needed (temperature, cacheRetention)
- [ ] Test model switching: `openclaw models list` and `/model` command
- [ ] Verify Capability Broker credential isolation with new providers
- [ ] Add cost tracking via `debug-dumper` plugin (provider + model in telemetry)
- [ ] Document in `general.md` once finalized

---

## References

- [OpenClaw Configuration Reference](https://docs.openclaw.ai/gateway/configuration-reference)
- [Model Providers](https://docs.openclaw.ai/concepts/model-providers)
- [Multi-Agent Routing](https://docs.openclaw.ai/concepts/multi-agent)
- [Model Failover](https://docs.openclaw.ai/concepts/model-failover)
- Current config: `infra/stacks/laptop-server/openclaw/openclaw.json.reference`
- Design doc: `docs/general.md` (LLM Backend Strategy section)
