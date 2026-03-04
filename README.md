# Corvus

**Security-first, local-first multi-agent system.**

Corvus is a self-hosted multi-agent framework that routes a single chat surface into domain-specific agents (work, personal, finance, homelab, music, docs, email). Built around zero-secret-exposure: an external credential manager holds all secrets, the LLM never sees auth tokens, and break-glass access is password-protected.

## Key Principles

- **Zero secret exposure** — Credentials live in an encrypted store (SOPS + age), never in prompts, tool args, or outputs
- **Capability Broker** — External credential manager exposes narrow typed tools; agents never touch raw secrets
- **Break-glass access** — Password-protected emergency override for privileged operations
- **Modular memory** — Obsidian vault as canonical store, with pluggable backends (Cognee, Remember.md)
- **Domain isolation** — Each agent gets its own workspace, session, and least-privilege tool policy
- **Model-agnostic** — Claude, OpenAI, Gemini, Kimi, local Ollama — switch at runtime

## Architecture

```
Internet → SWAG → Authelia SSO → Corvus Gateway (FastAPI + WebSocket)
                                       │
                        ┌───────────────┼───────────────┐
                        ▼               ▼               ▼
                   Router Agent    Domain Agents    Capability Broker
                   (intent →       (work, home,     (holds secrets,
                    dispatch)       finance...)      exposes safe tools)
```

## Status

> **Rename in progress (2026-02-28):** The codebase is being renamed from `claw` to `corvus`. Code and module paths still use `claw/` until the full rename pass is complete.

The project will be split into:
- **corvus** — Public framework (the agent system)
- **infra** — Private repo (homelab-specific deployment, stacks, configs)

## Tech Stack

- **Runtime:** Python 3.11+ (FastAPI, Claude Agent SDK)
- **Secrets:** SOPS + age encrypted-at-rest, external cred manager
- **Memory:** Obsidian vault + SQLite index + Cognee semantic search
- **Deployment:** Docker Compose via Komodo (GitOps)
- **Auth:** Authelia SSO + 2FA, OIDC for integrated services
- **Observability:** Grafana + Loki + Alloy

## License

TBD
