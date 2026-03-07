# Corvus — Architecture (formerly Claw)

> **RENAME IN PROGRESS (2026-02-28):** Claw → Corvus. Code/module names still use `claw/`. Full rename is a separate task.

> **Purpose of this file:** Drift prevention. Every design decision that matters is here.
> If something contradicts this file, this file wins. Update this file first, then the code.

---

## System Overview

Single Python process. FastAPI + WebSocket gateway wrapping the **Claude Agent SDK** (`claude-agent-sdk` on PyPI). 9 subagents (8 domain + 1 general). Skills-first tool exposure. Two-layer hybrid memory with Obsidian vault storage. Session stop hook extracts key facts on disconnect. **ACP integration** enables spawning external coding agents (Codex, Gemini CLI, etc.) as sandboxed sub-agents via the Agent Client Protocol.

```
Internet → SWAG (optiplex) → Authelia SSO → Claw Gateway (laptop-server:18789)
```

---

## Core Invariants

1. **100% Python.** No Node.js, no TypeScript, no additional runtimes.
2. **Skills + Scripts, not MCP** for domain tools. MCP only for Gmail and Home Assistant.
3. **No secrets in prompts, tool args, tool output, memory, or workspace files.** Ever.
4. **Obsidian vault is the canonical markdown store.** SQLite indexes it; vault is source of truth.
5. **Cognee handles all semantic/vector search.** No sqlite-vec, no llama-cpp-python, no local embedding models.
6. **Agents get least-privilege tools.** Email and Home agents have no Bash. Finance and Docs have no Read/Write.
7. **No mocks in tests.** No MagicMock, no monkeypatch, no @patch. Behavioral tests only — real DBs, real files, real containers, real HTTP. Testcontainers for external services.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Claw Gateway (Python)                       │
│                                                                 │
│  FastAPI (lifespan) ── WebSocket /ws (chat sessions)            │
│       │                POST /api/webhooks/{type} (one-shot)     │
│       │                GET /health · GET/PATCH /api/schedules   │
│       │                                                         │
│  ┌────▼───────────────────────────────────────────────────────┐ │
│  │          Claude Agent SDK (ClaudeSDKClient)                │ │
│  │                                                            │ │
│  │  RouterAgent → intent classification → domain dispatch     │ │
│  │  ModelRouter → backend selection with fallback chains      │ │
│  │  SDKClientPool → per-backend env resolution                │ │
│  │                                                            │ │
│  │  9 Subagents (AgentDefinition):                            │ │
│  │    personal · work · homelab · finance                     │ │
│  │    email · docs · music · home · general                   │ │
│  │                                                            │ │
│  │  Hooks (HookMatcher):                                      │ │
│  │    PreToolUse  → block .env reads, enforce tool policy     │ │
│  │    PostToolUse → sanitize output, structured event logs    │ │
│  └────────────────────────────────────────────────────────────┘ │
│       │                                                         │
│  ┌────▼───────────────────────────────────────────────────────┐ │
│  │  ACP Agent Bridge (CorvusACPClient)                       │ │
│  │                                                            │ │
│  │  AcpAgentRegistry → config-driven agent commands           │ │
│  │  AcpSessionTracker → session IDs, PIDs, resume state      │ │
│  │  JSON-RPC 2.0 over stdio → Codex, Gemini, OpenCode, etc. │ │
│  │                                                            │ │
│  │  7-layer enforcement:                                      │ │
│  │    L1 env strip · L2 workspace jail · L3 file gating      │ │
│  │    L4 terminal gating · L5 policy enforcement              │ │
│  │    L6 output sanitize · L7 process sandbox (no network)   │ │
│  └────────────────────────────────────────────────────────────┘ │
│       │                                                         │
│  ┌────▼───────────────────────────────────────────────────────┐ │
│  │  Infrastructure Layer                                      │ │
│  │                                                            │ │
│  │  ToolProviderRegistry → provider lifecycle + health checks │ │
│  │  AgentSupervisor → heartbeat loop, auto-restart (3 retries)│ │
│  │  EventEmitter → routing_decision, session, heartbeat events│ │
│  │  CredentialStore → SOPS decrypt → inject → sanitize        │ │
│  │  CronScheduler → scheduled tasks (daily digest, etc.)      │ │
│  └────────────────────────────────────────────────────────────┘ │
│       │                                                         │
│  ┌────▼───────────────────────────────────────────────────────┐ │
│  │  MCP Tool Servers (per-agent isolation)                    │ │
│  │                                                            │ │
│  │  email · drive · ha · paperless · firefly                  │ │
│  │  obsidian_personal · obsidian_work · obsidian_homelab ...  │ │
│  │  (Obsidian servers namespaced per agent with vault prefix  │ │
│  │   isolation — each agent only sees its allowed paths)      │ │
│  └────────────────────────────────────────────────────────────┘ │
│       │                                                         │
│  ┌────▼───────────────────────────────────────────────────────┐ │
│  │  Observability                                             │ │
│  │                                                            │ │
│  │  JSONLFileSink → /var/log/claw/events.jsonl → Alloy → Loki│ │
│  │  Grafana dashboard: fleet health, agent activity, security,│ │
│  │    sessions, models, webhooks                              │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Gateway Infrastructure

### Startup Sequence

```
_init_credentials()          # SOPS decrypt → inject env → register sanitizer patterns
_register_providers(registry) # HA, Paperless, Firefly, Obsidian, Google → ToolProviderRegistry
AgentSupervisor(registry, emitter)  # Wraps registry, starts heartbeat
CronScheduler(config, db, emitter)  # Loads schedule definitions
lifespan startup:
  supervisor.start()         # 30s heartbeat loop begins
  scheduler.load() + start() # Cron jobs activate
```

### ToolProviderRegistry (`claw/providers/registry.py`)

Central registry for all external tool providers. Each provider is a `ProviderConfig` with:
- `name` — unique identifier (e.g. `"ha"`, `"paperless"`)
- `env_vars` — required environment variables
- `health_check` — async callable returning `HealthStatus`
- `create_tools` — factory for SDK tool objects
- `restart` — optional async callable for auto-restart

Provider registration is data-driven via `_PROVIDER_DEFS` table in `server.py`. Providers are only registered when their gate env var is set.

### AgentSupervisor (`claw/supervisor.py`)

Monitors provider health on a 30-second heartbeat loop:
- Calls each provider's `health_check()` and emits `heartbeat` events with `mcp_status` map
- Auto-restarts unhealthy providers that have a `restart` callable
- Retry cap: `MAX_RESTART_ATTEMPTS = 3` per provider; counter resets when provider recovers to healthy
- `restart_provider(name)` — public API for manual restart (resets counter)
- `graceful_shutdown()` — cancels heartbeat task

### EventEmitter (`claw/events.py`)

Async event bus with pluggable sinks. Events emitted:
- `routing_decision` — agent, backend, source (websocket/webhook), query_preview
- `session_start` / `session_end` — user, session_id, duration, message_count
- `heartbeat` — provider health map every 30s
- `provider_restart` — provider name + attempt number
- `tool_use` / `tool_result` — from hooks

Default sink: `JSONLFileSink` writing to `/var/log/claw/events.jsonl` (shipped to Loki via Alloy).

### ModelRouter (`claw/model_router.py`)

Routes agents to LLM backends with fallback chains defined in `config/models.yaml`. `SDKClientPool` resolves the backend and builds the appropriate env vars for each SDK client.

### CronScheduler (`claw/scheduler.py`)

Cron-based task scheduling with SQLite-backed state. Supports daily digests, memory maintenance, and other periodic tasks. API: `GET/PATCH /api/schedules`, `POST /api/schedules/{name}/trigger`.

### Per-Agent MCP Isolation

Obsidian vault access is namespaced per agent via `AGENT_TOOL_ACCESS` config (`claw/agent_config.py`):
- Each agent gets its own `obsidian_{agent}` MCP server with `allowed_prefixes`
- Personal agent: `personal/`, work agent: `work/`, etc.
- Read/write permissions configured independently per agent
- Other MCP servers (email, drive, HA, paperless, firefly) are shared but only exposed to agents whose tool policy includes them

---

## Prompt Composition (OpenClaw-inspired)

Every agent gets the same layered prompt composition — no special cases:

```
Layer 0: Soul (shared)          ← claw/prompts/soul.md
         Identity + principles + memory operating instructions
         Counteracts CLI binary's hardcoded "You are Claude" injection

Layer 1: Agent Soul (per-agent) ← claw/prompts/souls/{agent}.md (via soul_file in YAML)
         Personality, vibe, behavioral style
         e.g. homelab = "methodical, cautious", music = "encouraging, patient"

Layer 2: Agent Identity          ← Generated from registry name
         "You are the **{name}** agent"

Layer 3: Agent Prompt            ← claw/prompts/{agent}.md (via prompt_file in YAML)
         Domain capabilities, behaviors, workflows

Layer 4: Sibling Agents          ← registry.list_enabled() (excludes self)
         Dynamic list of other available agents with descriptions

Layer 5: Memory Context          ← MemoryHub.seed_context() per agent domain
         Recent + evergreen memories from agent's readable domains
```

All composition happens in `AgentsHub._compose_prompt_layers()` — single source of truth.
`build_agent()` and `build_system_prompt()` both use `_compose_prompt()`.

**Extensibility:** Drop a new YAML in `config/agents/` with `prompt_file` and `soul_file`.
The registry auto-discovers it. The agent appears in every other agent's sibling list.

---

## Memory System

```
Query ──┬──→ Primary: BM25 (SQLite FTS5)
        │      Fast keyword matching on memories_fts table
        │
        ├──→ Overlays (optional): Cognee, sqlite-vec, etc.
        │      Fan-out writes, merge search results
        │      Graceful degradation → BM25-only if unavailable
        │
        └──→ Merge + Temporal Decay (30-day half-life, evergreen exempt)
               Return top-K results as JSON
```

**Storage:** SQLite at `DATA_DIR/memory/main.sqlite` (FTS5 for BM25).
**Domains:** Each agent owns a private domain (e.g. `homelab`, `finance`, `personal`).
**Visibility:** `private` (domain owner only) or `shared` (all agents can read).
**Evergreen:** Records with importance >= 0.9 are exempt from temporal decay.

### Memory Tools (per-agent MCP server)

Each agent gets a `memory_{agent}` MCP server with closure-captured identity:

| Tool | Purpose |
|------|---------|
| `memory_search` | BM25 search across readable domains |
| `memory_save` | Save to own domain (auto-set, can't override) |
| `memory_get` | Retrieve by ID with visibility enforcement |
| `memory_list` | Paginated list with domain/visibility filtering |
| `memory_forget` | Soft-delete (domain owner only) |

### Prompt Seeding

`MemoryHub.seed_context(agent_name)` synchronously fetches recent + evergreen memories
at agent spawn time. Injected into Layer 5 of prompt composition. Evergreen memories
appear first, then by temporal-decay-adjusted score.

### Domain Isolation

Write enforcement: agents can only write to their `own_domain` or `"shared"`.
Read enforcement: SQL-level `WHERE` clause filters by `readable_domains`.
Audit trail: all `save`/`forget` operations logged to `memory_audit` table.

---

## Subagent Tool Policy

| Agent | Tools | Why |
|-------|-------|-----|
| personal | Bash, Read | Journal, planning, memory via scripts |
| work | Bash, Read | Meeting notes, transcripts via scripts |
| homelab | Bash, Read, Grep, Glob | Full server ops, SSH, log queries |
| finance | Bash | Firefly III + YNAB API via scripts only |
| email | Bash, Gmail MCP | Inbox triage + Gmail API — confirm-gated send |
| docs | Bash | Paperless-ngx API via scripts only |
| music | Bash, Read | Practice logging via scripts |
| home | HA MCP tools only | No filesystem access — confirm-gated actions |
| general | Bash, Read | Cross-domain planning, memory search, Obsidian |

**All agents** get per-agent `memory_{agent}` MCP servers with `memory_search`/`memory_save`/`memory_get`/`memory_list`/`memory_forget` tools. Domain isolation enforced via closure-captured identity.

---

## ACP Agent Integration

External coding agents (Codex CLI, Gemini CLI, OpenCode, Claude Code) can be spawned as sandboxed sub-agents via the **Agent Client Protocol** (ACP) — a JSON-RPC 2.0 bidirectional protocol over stdio, created by Zed Industries.

### How It Works

ACP is a **second execution path** alongside the Claude Agent SDK. When a domain agent's spec declares `backend: acp`, the run executor spawns the configured ACP agent as a child process instead of using `ClaudeSDKClient`. Corvus acts as the ACP **client** — it controls the agent's file access, terminal commands, and permissions.

```
Router dispatch → backend: acp → CorvusACPClient
    → spawn codex-acp subprocess (stdio pipes)
    → initialize → session/new → session/prompt
    → agent streams session/update notifications
    → agent requests fs/read, fs/write, terminal/create → we serve or deny
    → prompt completes → same run_complete event as Claude path
```

### Security Model

ACP agents inherit a **restricted subset** of their parent agent's permissions (intersection, never union). 7-layer defense-in-depth:

| Layer | Mechanism | Blocks |
|-------|-----------|--------|
| L1 | Env stripping (no secrets in process env) | Secret exfiltration via env/printenv |
| L2 | Workspace jail (sandboxed cwd) | Host filesystem access |
| L3 | File gating (path validation + CapabilityRegistry) | Traversal attacks, secret files |
| L4 | Terminal gating (blocklist + always confirm-gated) | Dangerous commands, exfiltration |
| L5 | Permission policy (deny-wins via CapabilityRegistry) | Privilege escalation |
| L6 | Output sanitization (redact secrets in responses) | Data leakage via agent output |
| L7 | Process sandbox (no network, restricted PATH) | Rogue subprocesses, reverse shells |

### Observability

ACP `session/update` notifications translate to the same Corvus WebSocket event types (`run_output_chunk`, `tool_use`, `tool_result`, `thinking`, `confirm_request`). The frontend displays ACP agent activity identically to Claude agent activity — full traces, tool calls, streaming text.

### Configuration

ACP agents are registered in `config/acp_agents.yaml`. Domain agents opt in via their spec:

```yaml
# config/agents/homelab/agent.yaml
backend: acp
metadata:
  acp_agent: codex
```

### Key Components

| Component | Location |
|-----------|----------|
| `CorvusACPClient` | `corvus/acp/client.py` |
| `AcpAgentRegistry` | `corvus/acp/registry.py` |
| `AcpSessionTracker` | `corvus/acp/session.py` |
| ACP execution path | `corvus/gateway/run_executor.py` |
| Agent commands | `config/acp_agents.yaml` |

> Full design: `docs/plans/2026-03-06-corvus-cli-unified-isolation-design.md`

---

### Session Stop Hook

On WebSocket disconnect, the gateway:
1. Checks if session had 2+ user messages (skip trivial sessions)
2. Sends transcript to claude-haiku for memory extraction (max 5 memories)
3. Persists each memory to Obsidian vault + SQLite FTS5 via MemoryEngine
4. Never crashes teardown — all extraction errors are logged and swallowed

---

## Credential Management

```
~/.claw/
  credentials.json       # SOPS+age encrypted — all service credentials
  credentials.json.bak   # Previous version (rotation rollback)
  age-key.txt            # age private key (0600)
  passphrase.hash        # Argon2id hash of break-glass passphrase (0600)
  lockout.json           # Rate-limit state for failed passphrase attempts
```

**CredentialStore** (`claw/credential_store.py`) decrypts `credentials.json` at startup, holds values in memory, and calls each tool module's `configure()` function. If no credential file exists, falls back to env vars (Docker compose compat).

**Dynamic sanitization:** At startup, `sanitize.py` registers redaction patterns built from actual credential values — not just generic regex. Any credential that leaks into tool output gets caught.

**Credential rotation:** New value stored as pending → validated against service API → promoted to active. Old value kept as previous until next successful rotation.

### Break-Glass Mode

Gateway-level privilege escalation for emergency ops. **Invisible to all agents** — no system prompt, tool, or routing path references it. Only the gateway's tool-policy layer checks the flag.

- Activated via `/break-glass` chat command or `--break-glass` CLI flag
- Protected by Argon2id passphrase with escalating lockout (3 fails → 15 min, 6 → 1 hr, 9 → 24 hr)
- Per-session — auto-expires on disconnect
- Only works with models in the `trusted_models` allowlist
- All actions logged with `"break_glass": true` in audit trail

---

## Security Rules (Non-Negotiable)

1. PreToolUse hook blocks: `cat/head/tail/source *.env`, `Read` on `*.env`
2. Credentials encrypted at rest via SOPS+age in `~/.claw/credentials.json`
3. Tool modules get credentials via `configure()` at startup — agents never see raw values
4. Dynamic sanitization redacts actual credential values from all tool output
5. Gmail send/archive and HA service calls require explicit user confirmation
6. Docker socket mounted for homelab ops — group_add `988` (docker GID)
7. Break-glass mode is invisible to agents — gateway-only, passphrase-protected, rate-limited
8. ACP sub-agents inherit restricted subset of parent agent's permissions (intersection, never union)
9. ACP sub-agents never get credential_store access, secret access, or break-glass elevation
10. ACP sub-agent processes run with no network access (unshare/sandbox-exec) and restricted PATH
11. All ACP file operations validated against workspace boundary; all terminal commands always confirm-gated

---

## Deployment

- **Container:** `python:3.11-slim-bookworm` + Claude Code CLI + pip deps
- **Host:** localhost, port 18789
- **Auth:** Authelia trusted-proxy via SWAG on optiplex (X-Remote-User header)
- **Data:** `/data` mounted as `/data`
- **Vault:** `/mnt/vaults` mounted RW (Obsidian vault)
- **Logs:** `/var/log/claw/events.jsonl` → Alloy → Loki → Grafana
- **Limits:** 4G memory limit, 1G reservation

---

## What Is NOT In This System

- No Node.js, no TypeScript runtime (backend is 100% Python; ACP agents are spawned as external processes via `npx` but Corvus code is 100% Python)
- No sqlite-vec, no llama-cpp-python, no local embedding models
- No direct inter-agent delegation between Corvus domain agents (agents redirect via sibling list); ACP sub-agents are dispatched by the gateway, not by other agents
- No Corvus-as-ACP-agent (exposing Corvus to external editors) — future work
