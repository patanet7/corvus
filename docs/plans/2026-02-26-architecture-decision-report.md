# Architecture Decision Report: OpenClaw vs Custom Build

**Date:** 2026-02-26
**Status:** PENDING DECISION
**Context:** Before starting Slice 12 (Capability Broker), we paused to evaluate whether OpenClaw should remain the runtime — or whether a custom system built on Claude SDK + MCP would be a better path forward.

Three independent expert analyses were conducted. This report consolidates their findings.

---

## Executive Summary

OpenClaw provides **three things that actually matter**: a web UI, hybrid-search memory, and a persistent webhook endpoint. Everything else it offers — agent loop, tool registration, hooks, session management, permissions — is either commodity functionality available in Claude SDK/Claude Code, or reimplements what MCP already standardizes. The remaining ~30 hours of OpenClaw plugin work (Slices 12–20) would build deep coupling to a system we don't control.

**Recommendation:** Option B — Claude SDK + MCP servers. Build the core in 1–2 days, skip ~30 hours of OpenClaw-specific plugin development, and own the entire stack.

---

## What OpenClaw Actually Gives Us

| Capability | OpenClaw Provides | Alternative |
|-----------|-------------------|-------------|
| Web chat UI | Yes (Control UI) | Build or use Open WebUI (~1 day) |
| Agent loop (tool calling) | Yes | Claude SDK `messages.create()` with tools (~100 lines) |
| Hybrid search memory | Yes (memory-core: BM25 + vectors + MMR + temporal decay) | Rebuild with SQLite + sqlite-vec (~400-600 lines) |
| Tool registration | Plugin SDK `api.registerTool()` | MCP `server.tool()` — industry standard |
| Hooks (before/after tool) | Plugin events | Claude SDK tool execution wrapper (~20 lines) |
| Session management | Built-in | SQLite sessions table (~50 lines) |
| Sandbox execution | Docker containers | Docker API directly (~100 lines) |
| Multi-agent routing | Agent configs | Claude SDK with system prompts + tool subsets (~200 lines) |
| Credential isolation | Must build ourselves (Slice 12) | MCP server with env vars — already isolated by design |
| Webhook endpoint | Gateway HTTP server | Express/Fastify (~30 lines) |
| Permissions/ACL | Config-based | Implement in routing layer (~50 lines) |

**Key insight from the architect-reviewer:** The Capability Broker (Slice 12) IS an MCP server reimplemented as an OpenClaw plugin. Building it as MCP directly is simpler and portable.

---

## The Three Options

### Option A: Keep OpenClaw (Current Path)

**What we'd do:** Continue Slices 12–20 as planned. Build Capability Broker as an OpenClaw plugin. Build all domain agents as OpenClaw agent configs.

| Pros | Cons |
|------|------|
| Web UI works today | ~30+ hours of OpenClaw-specific plugin work remaining |
| Memory system already running | Deep coupling to a system we don't maintain |
| No migration cost | Plugin SDK is underdocumented, patterns discovered by reading source |
| Familiar from Slices 10-11 | Every new tool = OpenClaw plugin boilerplate |
| | Can't use Claude Code features (skills, MCP, teams) inside OpenClaw |
| | Maintenance burden: OpenClaw updates may break plugins |
| | DooD (Docker-outside-Docker) complexity for sandbox |

**Effort to finish:** ~30 hours (Slices 12–20)
**Ongoing maintenance:** High — tracking OpenClaw releases, fixing plugin breakage

### Option B: Claude SDK + MCP Servers (Recommended)

**What we'd build:** A ~1,600–2,000 line TypeScript system:

```
Custom System Architecture
─────────────────────────
┌──────────────────────────────────────────────┐
│                 Web UI Layer                  │
│         (Open WebUI / custom React)          │
└──────────────────┬───────────────────────────┘
                   │ HTTP/WebSocket
┌──────────────────▼───────────────────────────┐
│              Gateway Server                   │
│  - Express/Fastify (~30 lines)               │
│  - Authelia trusted-proxy auth (reuse SWAG)  │
│  - Session management (SQLite)               │
│  - Webhook endpoint                          │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│             Agent Orchestrator                │
│  - Claude SDK messages.create() loop         │
│  - Router: system prompt + intent dispatch   │
│  - Domain agents: separate system prompts    │
│  - Tool subsets per agent (security boundary) │
│  - ~200-300 lines                            │
└──────────────────┬───────────────────────────┘
                   │ MCP (JSON-RPC over stdio)
┌──────────────────▼───────────────────────────┐
│           MCP Tool Servers                    │
│  ┌─────────────┐ ┌───────────┐ ┌───────────┐│
│  │ Obsidian    │ │ Paperless │ │ Firefly   ││
│  │ (read/write)│ │ (search)  │ │ (txns)    ││
│  └─────────────┘ └───────────┘ └───────────┘│
│  ┌─────────────┐ ┌───────────┐ ┌───────────┐│
│  │ Homelab     │ │ Gmail     │ │ Memory    ││
│  │ (Komodo/TS) │ │ (triage)  │ │ (search)  ││
│  └─────────────┘ └───────────┘ └───────────┘│
│  Each server: own process, own env vars,     │
│  own credentials. Isolation by design.       │
└──────────────────────────────────────────────┘
```

| Pros | Cons |
|------|------|
| Own the entire stack — no upstream breakage risk | Must build/adopt a web UI |
| MCP tools work everywhere (Claude Code, VS Code, Cursor, LangChain) | Must rebuild hybrid search memory (~400-600 lines) |
| Credential isolation is free (each MCP server = own process + env) | Initial build effort: 1-2 days core, 4-5 days with memory |
| Claude SDK is Anthropic's primary supported interface | No pre-built sandbox (use Docker API directly) |
| Skip ~30 hours of OpenClaw plugin boilerplate | |
| Can use Claude Code for dev while building the web system | |
| Each MCP server is independently testable and deployable | |
| Community MCP servers available for common integrations | |
| Future-proof: MCP is the emerging standard | |

**Effort breakdown:**

| Component | Lines | Time |
|-----------|-------|------|
| Gateway server (HTTP + auth + sessions) | ~200 | 2-3 hours |
| Agent orchestrator (Claude SDK loop + routing) | ~300 | 3-4 hours |
| Memory MCP server (hybrid search rebuild) | ~500 | 8-12 hours |
| Obsidian MCP server | ~150 | 2-3 hours |
| Homelab MCP server (Komodo, Tailscale, Docker) | ~300 | 4-6 hours |
| Web UI integration | ~200 | 4-6 hours |
| **Total** | **~1,650** | **~24-34 hours** |

**But:** The memory rebuild is optional initially — can start with markdown file search and add vector search incrementally. **Minimum viable: 1-2 days.**

### Option C: Claude Code as Runtime

**What we'd do:** Use Claude Code itself (the CLI tool) as the agent runtime. MCP servers for tools. CLAUDE.md for memory. Skills for workflows.

| Pros | Cons |
|------|------|
| Zero build effort for core | No web UI (terminal only) |
| MCP servers work natively | No persistent server (no webhook endpoint) |
| Skills, hooks, teams already built | No mobile/tablet access |
| Auto-memory, CLAUDE.md already working | Can't serve other users |
| Perfect for development/homelab ops | Session management is file-based |

**Best for:** Development workflows and CLI-first usage. Not suitable as the primary "personal assistant" with web access.

---

## Memory System Portability Assessment

The memory system (Slice 11) is the deepest OpenClaw coupling point.

| Layer | Coupling | Migration Effort |
|-------|----------|-----------------|
| Markdown files (MEMORY.md, evergreen, daily logs) | **Zero** — plain files on disk | Copy files, done |
| Session-memory hook (saves context on /new) | **Low** — 20 lines of logic | Rewrite as gateway middleware |
| Command-logger hook | **Low** — structured JSON append | Rewrite as gateway middleware |
| Hybrid search engine (BM25 + vectors + MMR + temporal decay) | **HIGH** — 400-600 lines inside memory-core | Rebuild with SQLite + sqlite-vec + node-llama-cpp |
| Embedding model (EmbeddingGemma 300M GGUF) | **Zero** — model file on disk | Same model, same node-llama-cpp loader |
| Boot-md hook | **Low** — loads MEMORY.md into system prompt | System prompt concatenation |

**Total migration for full parity:** 7-12 days
**Minimum viable (BM25 only, no vectors):** 4-5 days
**Recommendation:** Don't rebuild memory first. Start with file-based search, add hybrid search as a dedicated MCP server incrementally.

---

## Decision Framework

Answer these three questions:

### 1. How important is the web UI?

- **Critical (daily use, mobile access):** Option B — build a simple web UI or adopt Open WebUI
- **Nice to have:** Option B or C — start with Claude Code (Option C), build web UI later
- **Don't need it:** Option C — Claude Code is already working

### 2. How much do you want to own?

- **I want to understand every line:** Option B — ~1,600 lines you write and control
- **I want features fast, don't care about internals:** Option A — OpenClaw has the features, accept the coupling
- **I want minimum maintenance:** Option C — Anthropic maintains Claude Code

### 3. How do you feel about the next 30 hours of OpenClaw plugin work?

- **Excited, let's build:** Option A
- **That's 30 hours of coupling I don't want:** Option B
- **I'd rather spend that time on the MCP servers themselves:** Option B

---

## Recommended Path: Option B with Staged Migration

Don't rip out OpenClaw today. Instead:

### Phase 1: Build MCP servers (this week)
- Build Obsidian MCP server (works with Claude Code NOW and with custom system LATER)
- Build Homelab MCP server (same portability)
- Build any other tool servers needed
- **These are useful immediately** in Claude Code sessions

### Phase 2: Build the custom gateway (next week)
- Gateway server with Authelia auth (reuse SWAG setup)
- Agent orchestrator with Claude SDK
- Session management (SQLite)
- Wire up the MCP servers

### Phase 3: Migrate memory (when needed)
- Start with file-based search (grep over markdown)
- Add BM25 via SQLite FTS5
- Add vector search via sqlite-vec when you want semantic recall
- Port the existing SQLite database if it has valuable indexed content

### Phase 4: Retire OpenClaw
- Move web UI to custom or Open WebUI
- Shut down OpenClaw gateway container
- Remove OpenClaw-specific configs

**Key advantage of this path:** Every MCP server built in Phase 1 works with both OpenClaw (via adapter) AND the custom system. Zero wasted work.

---

## Appendix: What Each Expert Said

### Architect-Reviewer (Abstraction Boundaries)
> Build the Capability Broker as an MCP server with a thin (~40 line) OpenClaw adapter. Only abstract tool definitions and credentials via MCP. Do NOT abstract hooks, memory, config, or workspace files — YAGNI. Migration cost with MCP: 3-5 days. Without: 2-3 weeks.

### LLM-Architect (Memory Portability)
> Memory migration is 7-12 days for full parity, 4-5 days minimum viable. Hardest piece is the hybrid retrieval engine (~400-600 lines). The markdown files and embedding model have zero coupling. Recommended NOT migrating memory now — finish feature slices first, then migrate if needed.

### LLM-Architect (SDK Comparison)
> OpenClaw only provides 3 things that matter: web UI, hybrid search memory, webhook endpoint. Everything else (agent loop, tool registration, hooks, session management) is commodity. Claude SDK + MCP is ~1,600-2,000 lines total, 1-2 days for core. Slices 12-20 (~30+ hours) become unnecessary — the Capability Broker IS an MCP server, domain agents are just system prompts + tool subsets.
