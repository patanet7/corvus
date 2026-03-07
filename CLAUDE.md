# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Corvus** (Latin for crow — intelligent, tool-using, security-aware) is a local-first, self-hosted, security-first multi-agent gateway. A single chat surface routes into domain-specific agents (work, personal, finance, homelab, music, docs/paperless, email). Built on Python + FastAPI + WebSocket + claude-agent-sdk.

## Testing Policy — NO MOCKS

**No MagicMock. No monkeypatch. No @patch. No unittest.mock. No fakes.**

All tests must be **behavioral** — exercise the real system with real setup/teardown:
- **Database tests**: Create a real SQLite DB, seed it, query it, verify results, tear down
- **Vault/filesystem tests**: Write real files to a temp directory, verify contents on disk
- **CLI tests**: Run scripts as real subprocesses, verify JSON stdout contracts
- **API tests**: Use **testcontainers** for services (Paperless, Firefly, etc.)
- **Auth tests**: Real HTTP requests against a real running server

Tests must verify **contracts** (input shape → output shape, status codes, required fields) not implementation details. If a test can't run without mocking, the code needs refactoring, not the test.

## Task Runner — mise

**Always use `mise run` for project tasks.** The `mise.toml` at project root defines all standard commands:

```bash
mise run serve              # Start gateway server
mise run test               # Run all tests
mise run test:gateway       # Gateway tests only
mise run test:contracts     # Contract tests only
mise run lint               # Lint with ruff
mise run format             # Format with ruff
mise run setup              # Interactive setup wizard
mise run setup:status       # Credential status dashboard
mise run break-glass        # Start server in break-glass mode
```

## Package Management

**Always use `uv` for package operations**, not bare `pip`:
- Add a dependency: `uv add <package>`
- Remove a dependency: `uv remove <package>`
- Sync/install from lockfile: `uv sync`
- Upgrade a dependency: `uv lock --upgrade-package <package> && uv sync`
- The lockfile (`uv.lock`) and `pyproject.toml` are the sources of truth — never edit `requirements.txt` directly

## Runtime — Python Only

**Corvus is a Python application.** The entry point is `python -m corvus.server` (FastAPI + WebSocket), run via `mise run serve`. The `claude-agent-sdk` Python SDK communicates with the Claude Code CLI under the hood, but our code is 100% Python.

**Always use `uv run python`** (not bare `python3`) when running Python scripts or commands outside of mise tasks.

**Do NOT** use Node.js commands (`node`, `npm`, `npx`) in Docker compose, scripts, or deployment. Let the Dockerfile's `CMD ["python", "-m", "corvus.server"]` run instead.

## Repository Structure

```
corvus/              — Python gateway package (FastAPI + WebSocket + agents)
frontend/            — SvelteKit chat UI
tests/               — Behavioral test suite (1790+ passing, no mocks)
scripts/             — CLI tools for agent domains (finance, paperless, etc.)
config/              — Agent definitions, model routing, capabilities (deployment-specific)
config.example/      — Example configs for new deployments
mcp_servers/         — MCP server implementations (Gmail, HA)
Dockerfile           — Multi-stage hardened build (non-root)
docker-compose.yaml  — Quick-start compose for local dev
ARCHITECTURE.md      — Gateway architecture diagram + component docs
.env                 — Symlink to secrets file (gitignored)
```

## Credential & Secret Handling

**CRITICAL RULES:**

1. **NEVER read `.env` files.** Secrets must never appear in tool output.
2. **NEVER type, paste, echo, or inline passwords/tokens/keys in bash commands.**
3. **Service credentials** (API keys, tokens) live in `.env` (gitignored). If a service needs a credential at runtime, it reads from env vars — never from Claude Code.
4. If a new credential is needed, tell the user to add it to `.env` manually — never write secrets yourself.

## Architecture Summary

### Core Components
- **Corvus Gateway** — Central runtime handling routing, tool policy, and session management
- **Router Agent (Huginn)** — Intent classification and dispatch (minimal tools: sessions only)
- **Domain Agents** — Isolated agents per domain (work, homelab, finance, docs, inbox, personal, music), each with separate workspace, sessions, and tool policies
- **Capability Registry** — Security layer: typed tool policies, deny-wins-over-allow

### Memory Architecture
- **FTS5 Backend**: SQLite full-text search with BM25 ranking, MMR diversity, temporal decay
- **Cognee Backend** (optional): Graph-backed recall via cognee plugin
- **Obsidian Vault**: Markdown files for persistent knowledge
- Cross-domain sharing only via explicit `readable_domains` in agent config

### Prompt Composition (6 layers)
1. Soul (base personality)
2. Agent Soul (domain-specific personality)
3. Identity (name, description, capabilities)
4. Prompt (domain instructions)
5. Siblings (awareness of other agents)
6. Memory (seeded context from MemoryHub)

## Multi-Backend Model Routing

**Corvus uses LiteLLM proxy for model routing.** At startup, `LiteLLMManager` generates a `litellm_config.yaml` from `config/models.yaml` and starts a local proxy on `127.0.0.1:4000`. The `claude-agent-sdk` talks to this proxy via `ANTHROPIC_BASE_URL`.

- **Claude**: Direct Anthropic API via LiteLLM
- **Ollama**: Routed by LiteLLM to local Ollama instance
- **Kimi**: Routed through KimiProxy (`localhost:8100`) registered as LiteLLM backend
- **OpenAI / Groq / etc.**: Add to `config/models.yaml` backends section

LiteLLM handles fallbacks, retries, cooldowns, and cost tracking. `config/models.yaml` is the single source of truth.

## Design Principles
- Default-deny tooling; deny wins over allow
- Sandbox-by-default for all tool execution
- Domain isolation: separate workspaces, sessions, and auth per agent
- All mutations require explicit approval and produce audit trails
- NO LAZY IMPORTS — solve the issue at module level
- NO RELATIVE IMPORTS

## Git Remotes

```bash
git push origin main      # GitHub (public)
git push forgejo main     # Forgejo (via SSH proxy)
```

Forgejo push requires:
```bash
GIT_SSH_COMMAND="ssh -o ProxyCommand='ssh -W localhost:2222 <user>@<tailscale-ip>'" git push forgejo main
```
