---
number: 4
title: "LiteLLM proxy for multi-backend model routing"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0004: LiteLLM Proxy for Multi-Backend Model Routing

## Context

Corvus needs to route different agents to different LLM backends (Claude via Anthropic API, Ollama for local models, Kimi via KimiProxy, OpenAI, Groq). Each backend has its own API format, auth mechanism, and error handling. Building per-backend adapters in the gateway would be significant ongoing maintenance.

## Decision

Use LiteLLM as a local proxy on `127.0.0.1:4000`. At startup, `LiteLLMManager` generates `litellm_config.yaml` from `config/models.yaml` and starts the proxy. The `claude-agent-sdk` talks to LiteLLM via `ANTHROPIC_BASE_URL`. LiteLLM handles format translation, fallbacks, retries, cooldowns, and cost tracking.

## Alternatives Considered

- **Direct per-backend API clients**: Rejected due to maintenance burden of tracking API changes across multiple providers.
- **OpenRouter**: Rejected because it adds an external dependency and network hop for what can run locally.
- **Custom proxy layer**: Rejected because LiteLLM already handles format translation, fallback chains, and cost tracking.

## Consequences

- `config/models.yaml` is the single source of truth for all model routing configuration.
- Adding a new backend requires only a YAML entry, not code changes.
- LiteLLM proxy is an additional process to manage at startup.
- Cost tracking and fallback logic are delegated to a well-maintained open-source project.
