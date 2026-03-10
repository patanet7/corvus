---
title: "Corvus Implementation Master Index"
type: plan
status: superseded
date: 2026-03-07
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# Corvus Implementation — Master Index

> **Last audit:** 2026-03-07 (incremental update — cleanup tasks completed, code-level DRY fixes)
>
> Each section is organized around the project's core pillars: **security verification**, **extensibility**, **evolving agents**, **parallel execution**, and **cron/automation**. Priorities reflect deployability parity with production multi-agent systems (OpenClaw, AutoGen, CrewAI, LangGraph).

---

## Completed Slices (Infrastructure)

| # | Slice | Completed | Deliverable |
|---|-------|-----------|-------------|
| 01 | Tailscale Mesh | 2026-02-23 | All nodes on encrypted mesh VPN with deny-by-default ACL |
| 02 | Forgejo Git Forge | 2026-02-23 | Git forge running, compose files versioned, infra repo |
| 03 | Komodo Fleet Management | 2026-02-23 | Core + Periphery on all hosts, autodeploy on push |
| 04 | Observability Stack | 2026-02-24 | Loki + Grafana + Alloy shipping logs from all hosts |
| 05 | Backup Infrastructure | 2026-02-24 | Restic on NAS, Ofelia cron, pg_dump, Healthchecks |
| 06 | NAS NFS Mounts | 2026-02-24 | NFS exports, fstab hardened, NOPASSWD sudo, SSH keys |
| 07 | Service Migrations | — | SKIPPED — services already on correct hosts |
| 08 | Secrets & Authelia SSO | 2026-02-25 | SOPS+age secrets, Authelia SSO + 2FA + OIDC |
| 09 | Cleanup & Renovate | 2026-02-25 | Watchtower removed, Renovate via Forgejo Actions |

## Completed Slices (Gateway)

| # | Slice | Completed | Deliverable |
|---|-------|-----------|-------------|
| 10 | [Corvus Gateway](./10-openclaw-gateway.md) | 2026-02-25 | FastAPI + WebSocket gateway, trusted-proxy auth, sandbox-by-default |
| 11 | [Memory System](./11-memory-system.md) | 2026-02-26 | SQLite FTS5 + Cognee hybrid search, session memory extraction |
| 12 | [Capability Broker](./12-capability-broker.md) | 2026-02-27 | Obsidian tools, shared sanitize.py, 9-part isolation suite, 114 tests |
| 10A | Hardening & Model Routing | 2026-02-28 | CapabilitiesRegistry, AgentSupervisor (auto-restart), EventEmitter, ModelRouter, Grafana dashboard |
| 10B | Domain Agent Buildout | 2026-02-27 | Paperless + Firefly MCP tools, webhooks, routing audit (**confirm-gating: UI only, NOT wired to SDK — see P0 security**) |
| 13 | Personal Agent | 2026-02-27 | Obsidian-remote, vault structure, persona, per-agent path isolation |
| 13b | Scheduling | 2026-02-28 | CronScheduler, DB-backed schedules, REST API, WebSocket push (**endpoints unauthenticated — see P0 security**) |

## Completed (Post-Slice)

| Feature | Completed | Deliverable |
|---------|-----------|-------------|
| Hub Architecture | 2026-03-02 | AgentsHub, CapabilitiesRegistry, MemoryHub with resolver wiring |
| Backend Modularization | 2026-03-03 | server.py -> runtime.py + options.py + distributed API routes |
| ChatSession Extraction | 2026-03-03 | ChatSession class with TurnContext, send, execute_agent_run, dispatch_control_listener, async interrupt queue |
| Prompt Composition | 2026-03-03 | 6-layer system (soul -> agent soul -> identity -> prompt -> siblings -> memory) |
| Per-Agent Souls | 2026-03-03 | Per-agent personality files, soul_file in YAML spec, MemoryHub prompt seeding |
| Generic Prompts | 2026-03-03 | All personal references removed from prompts (config.py still has `ALLOWED_USERS = "patanet7"`) |
| Frontend Chat UI | 2026-03-04 | 58 Svelte components, WebSocket chat, agent workspace, memory panel, trace timeline, 4 themes |
| Code Cleanup Sprint | 2026-03-07 | Claw→Corvus docstring rename (22 files), dead config constants removed, SERVICE_ENV_MAP unified as single source of truth, Obsidian dedup (~150 lines), stale plans archived, ARCHITECTURE.md updated, pytest markers on all integration tests, legacy mcp_servers archived |

---

## P0 — Security Verification (BLOCKING)

These must be fixed before any open-source exposure or production trust.

| Task | Status | Detail |
|------|--------|--------|
| **Wire confirm gate to SDK** | DONE (verified 2026-03-07) | Fully wired: `options.py:318-340` sends `confirm_request` via WS, blocks on `ConfirmQueue.wait_for_confirmation()`, returns `PermissionResultDeny` on denial/timeout. Frontend handles `confirm_request`/`confirm_response` in protocol layer. `chat_session.py` creates `ConfirmQueue` per session, `dispatch_orchestrator.py` cancels pending on disconnect. |
| **Add auth to schedule endpoints** | NOT DONE | `corvus/api/schedules.py` has NO `Depends(get_user)`. Anyone who can reach the gateway can list, modify, or trigger schedules. |
| **Fix duplicate route** | NOT DONE | Both `sessions.py` and `control.py` register `GET /api/dispatch/active`. The `sessions.py` version has a lazy import from `corvus.server` creating circular dependency risk. |
| **Webhook secret timing-safe comparison** | Not verified | `verify_webhook_secret()` should use `hmac.compare_digest()` to prevent timing attacks. Audit and fix if needed. |
| **Audit `.env` files in `infra/stacks/`** | NOT DONE | 6 `.env` files committed inside `infra/stacks/`. Must verify none contain real secrets before any public repo work. |
| **Remove hardcoded personal data** | Partial | `config.py` line 39: `ALLOWED_USERS = "patanet7"`. Grep for all `patanet7`, `absolvbass.com`, specific IPs. |

## P0 — CI Pipeline (BLOCKING)

No automated quality gate exists. Untested code deploys directly to production via Komodo autodeploy.

| Task | Status | Detail |
|------|--------|--------|
| **Create Forgejo Actions CI workflow** | NOT DONE | Must run `ruff check`, `pytest` (non-integration), and `mypy` on push/PR. 30 min of work, massive ROI. |
| **Add pytest-cov** | NOT DONE | 1857 tests with zero coverage measurement. Add `pytest-cov`, configure `[tool.coverage]` in pyproject.toml, set `fail_under = 70`. |
| **Add frontend CI** | NOT DONE | Must run `pnpm check`, `pnpm test`, build validation on push/PR. |
| **Add CI artifact upload** | NOT DONE | Test logs and Playwright traces should be preserved. |

---

## P1 — Agent Evolution & Extensibility

Making agents truly autonomous, evolving, and independently capable.

### Agent Runtime Capabilities

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Non-Claude backend capabilities | Broken | P1 | `options.py` strips ALL tools, hooks, agents, MCP servers for non-Claude backends. Ollama/OpenAI-compat models are chat-only. This contradicts "multi-backend" architecture. Fix: implement tool-calling for OpenAI-compat API format. |
| Model routing contract test | Not started | P1 | Prove model override roundtrip works end-to-end (UI -> WS -> backend -> SDK -> response with correct model metadata). |
| Agent hot-evolution | Not started | P1 | Agents should be able to modify their own prompt/soul/config based on learned patterns. YAML update API exists (`PATCH /api/agents/{name}`) but no agent-initiated self-modification loop. |
| Agent self-assessment | Not started | P2 | Periodic agent self-evaluation: "what am I good at, what should I delegate, what tools am I missing?" Feed into soul/prompt evolution. |
| Agent capability discovery | Not started | P2 | Agents should discover new tools/modules dynamically. Currently static YAML binding. |

### Plugin Architecture

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Plugin base classes | NOT DONE | P1 | Design doc describes `corvus/plugins/base.py` (ToolPlugin, MemoryPlugin ABCs) but no code exists. `corvus/plugins/` directory doesn't exist. |
| Plugin loader + registry | NOT DONE | P1 | Entry-point discovery for pip-installable plugins. Design exists but zero implementation. |
| Tool registration pattern | NOT DONE | P1 | Current tools are hardcoded imports in capabilities registry. Need a registration pattern that allows drop-in tools. |
| ComposeManifest for plugin services | NOT DONE | P2 | Plugins that need backing Docker services (e.g., Cognee needs Neo4j) should declare compose fragments. Design exists, not implemented. |

**Recommendation:** For V1, skip separate pip-installable plugins. Keep tools in `corvus/tools/` with a simple registry pattern. Entry-point plugin system comes when there's community demand.

### ChatSession Decomposition

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Extract confirm gate handler | DONE (verified 2026-03-07) | ~~P0~~ | Fully wired via `ConfirmQueue` + `options.py` `can_use_tool` callback. Sends WS `confirm_request`, blocks, respects deny/timeout. |
| Extract dispatch orchestrator | Not started | P1 | `execute_dispatch_runs` and parallel fan-out logic should be a separate `DispatchOrchestrator` class. |
| Extract event persistence | Not started | P2 | Session/run/trace event persistence methods should be a separate `EventPersistence` class. |
| Extract WebSocket protocol | Not started | P2 | Message loop, ping/pong, init handshake into `WSProtocol` class. |

---

## P1 — Parallel Execution & Dispatch

Making multi-agent dispatch production-grade.

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Supervisor queue UX | Not started | P1 | Long-running/background dispatches need pause/resume, reassignment, stale-run triage in UI. |
| Dispatch pause/resume backend | Not started | P1 | Frontend has `dispatchPaused` toggle but it's decorative — no backend effect. Wire to real dispatch lifecycle. |
| Cross-agent coordination tools | Not started | P1 | Agents need `sessions_send`, `sessions_list` tools (OpenClaw pattern) so agents can delegate to each other at runtime, not just via router. |
| Parallel dispatch monitoring | Not started | P2 | Real-time visualization of parallel agent runs with dependency graphs, fan-out/fan-in status. |
| Agent-to-agent delegation | Not started | P2 | Agent A discovers mid-task that Agent B should handle part of the work. Runtime handoff without user intervention. |
| Dispatch retry/recovery | Not started | P2 | Failed dispatch runs should support retry with configurable backoff. Currently orphaned on failure. |
| WebSocket reconnection safety | Not started | P2 | In-flight dispatches can be orphaned on WS drop. Need sequence numbering, dedup on reconnect, resume-from-last-ack. |

---

## P1 — Cron, Automation & Background Tasks

Making agents autonomous with scheduled and event-driven work.

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Schedule endpoint auth | NOT DONE | P0 | See Security section — currently unauthenticated. |
| Cron-driven agent tasks | Partial | P1 | CronScheduler exists but only triggers background dispatches. Need: agent-initiated cron (agent requests recurring work), result persistence, notification on completion/failure. |
| Webhook-to-agent pipeline | Partial | P1 | Webhook endpoints exist but limited to transcript/email/paperless/finance types. Need generic webhook-to-agent routing for arbitrary event sources. |
| Gmail PubSub | Not started | P2 | Real-time email via Google push -> webhook -> email agent. |
| Memory hygiene cron | Not started | P2 | Monthly cleanup, verify MEMORY.md consistency, Healthchecks ping, stale record pruning. |
| Agent heartbeat & health | Partial | P2 | AgentSupervisor exists but only monitors process health. Need: semantic health (is the agent producing useful output?), staleness detection, auto-restart with notification. |
| Event-driven triggers | Not started | P2 | Beyond cron: file-watch triggers (new Paperless doc), state-change triggers (HA entity change), integration triggers (Git push). |

---

## P1 — Deployment & Distribution

Every competitor publishes to a package registry. This is the biggest gap.

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Add `[build-system]` to pyproject.toml | NOT DONE | P1 | Can't even `pip install .` today. Need setuptools backend. |
| Add `[project.scripts]` entry point | NOT DONE | P1 | `corvus = "corvus.server:main"` for CLI invocation. |
| Module rename (claw -> corvus) | Partial (2026-03-07) | P1 | Docstrings/comments renamed in 22 source files. Python package already named `corvus/`. Remaining: Docker image labels, Komodo stack names, any remaining `claw` log labels. Kimi bridge API identifiers (`api-claw`, `X-Kimi-Claw-Version`) are external — leave as-is. |
| Add `.dockerignore` | NOT DONE | P1 | Currently copies .venv, frontend/node_modules, .git, tests into Docker build context. 5 min fix, big impact. |
| Docker image hardening | NOT DONE | P1 | Runs as root, ships dev deps (pytest/ruff/mypy), `curl \| bash` for Claude CLI (no pinned version/checksum). Fix: multi-stage build, non-root user, split prod/dev requirements. |
| Split requirements.txt prod/dev | NOT DONE | P1 | Dockerfile installs pytest, ruff, mypy in production image. Separate `requirements.txt` (prod) from `requirements-dev.txt` (dev), or use `pyproject.toml` with `[dev]` extras. |
| PyPI publishing | NOT DONE | P2 | Package as `corvus-gateway` on PyPI. Needs: build-system, entry points, version management, release workflow. |
| Setup wizard (`corvus setup`) | NOT DONE | P2 | Interactive first-time onboarding (agents, model, memory, plugins, prompts). Design exists, not implemented. |
| Public docs site | NOT DONE | P2 | MkDocs or similar from existing markdown. API reference auto-gen from FastAPI OpenAPI schema. |
| Version management | NOT DONE | P2 | Static `version = "0.1.0"` in pyproject.toml. Need: semantic versioning, changelog, release workflow. |

---

## P1 — Frontend Architecture

The frontend is surprisingly mature (8/10) but has structural risks that will compound.

### Structural Refactoring

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Extract +page.svelte god component | NOT DONE | P1 | 717-line god component with 20-field `agentWorkspace` object, duplicate `refreshAgentDirectory`/`selectWorkspaceAgent` functions. Extract into `AgentWorkspaceController` reactive class. |
| Decompose AgentWorkspaceShell | NOT DONE | P1 | 810 lines, 19 derived computations, 12 local interfaces. Split each tab (chat/tasks/config/validation) into own wrapper component. Extract derived computations into presenter module. |
| Deduplicate `toSession()` | NOT DONE | P2 | Defined in both `api/agents.ts` and `api/sessions.ts` as separate private functions doing the same thing. Extract to shared `api/mappers.ts`. |
| Centralize fetch with shared API client | NOT DONE | P2 | Each module calls `fetch()` directly except `memory.ts`. Create `fetchApi()` wrapper for JSON parsing, error creation, auth header injection, timeout. |
| Add AbortController to API calls | NOT DONE | P2 | `refreshAgentDirectory()` fires 6+ concurrent calls. Quick agent switching can cause stale responses to overwrite fresh data. |
| Verify Map reactivity in stores | NOT DONE | P2 | `pendingToolCalls` uses `Map<string, ToolCall>` inside `$state`. Svelte 5 may not track Map `.set()`/`.delete()` mutations. Potential subtle bug. |

### Missing Features

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| URL routing for modes/agents | NOT DONE | P1 | Entire app is single SvelteKit page with local state. Can't bookmark `/#agents/homelab` or share a link to a specific workspace. Use SvelteKit `goto()` + query params. |
| In-chat slash commands | Partial | P1 | `/new`, `/clear`, `/sessions` defined but only some wired. Missing: `/status`, `/compact`, `/usage`, `/reset` (table stakes for chat systems). |
| File attachment backend wiring | NOT DONE | P2 | `stageFiles()` creates `DraftAttachment` objects, shows toast warning. Need multipart upload endpoint + ingestion pipeline. |
| Voice capture backend wiring | NOT DONE | P2 | `stageVoiceCapture()` shows toast warning. Need Speaches STT/TTS integration. |
| Mobile responsiveness | NOT DONE | P2 | Fixed 48px mode rail, sidebar widths. No responsive breakpoints below 1024px. |
| Per-session cost tracking | NOT DONE | P2 | OpenClaw and LangSmith both offer this. EventEmitter has the data, need aggregation + UI. |

### Testing Gaps

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Protocol type centralization | NOT DONE | P1 | Shared types for WS init, API responses — prevent frontend/backend drift. |
| Frontend unit test coverage | Thin | P1 | Only ~10 unit test files for 58+ components. Component-level regressions not caught. |
| Accessibility audit | NOT DONE | P1 | `aria-label`/`aria-live` present on key elements but no systematic WCAG audit. Focus trap, keyboard nav, screen reader testing needed. |
| Backend-frontend contract tests | Partial | P1 | Some contract tests exist. Need: model override roundtrip, confirm gate behavior, policy enforcement flow. |
| E2E: policy enforcement flow | NOT DONE | P2 | Prove tool calls are allowed/denied/confirm-gated according to agent policy (real backend + real model). |
| Performance: large transcript | NOT DONE | P2 | Render budget for large transcripts and session list responsiveness. |

---

## P2 — Memory Enhancements (Slice 20)

Each item is independently deliverable.

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Cognee graph overlay | In progress | P2 | MemoryHub overlay wiring + Cognee backend + backend status API. Docker dataset orchestration pending. |
| MMR diversity re-ranking | NOT DONE | P2 | `config.mmr_lambda` exists but is unused. Implement Maximal Marginal Relevance in MemoryHub search. |
| Context compression | Not started | P2 | Anchored iterative summarization at 75% context. OpenClaw's pre-compaction memory flush is the reference pattern. |
| Remember.md plugin | Not started | P2 | Transcript -> PARA-structured Obsidian notes. |
| Memory connection pooling | Not started | P3 | FTS5Backend creates new `sqlite3.connect()` per operation. Fine for single-user, inefficient at scale. |
| `seed_context` abstraction fix | Not started | P3 | `hub.py:407` reaches through public API to call `primary._list_sync`. Breaks backend abstraction. |

---

## P2 — Documentation & Open-Source Readiness

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Fix ARCHITECTURE.md drift | DONE (2026-03-07) | P1 | Fixed: paths, agent count, Claw→Corvus refs, CapabilitiesRegistry docs, credential flow, LiteLLM proxy section. Remaining: `_compose_prompt_layers` comment numbering (P3). |
| API reference generation | NOT DONE | P2 | FastAPI auto-generates OpenAPI schema but most endpoints don't use Pydantic request/response models, so schema is minimal. Add Pydantic models to improve auto-docs. |
| Create README for open-source | NOT DONE | P2 | Need: quick-start, features, screenshots, architecture overview, contributing guide. |
| Pre-split personal data checklist | NOT DONE | P2 | Systematic grep for `patanet7`, `absolvbass.com`, specific IPs, hardcoded paths. Create checklist. |
| Decision: frontend in-repo or separate | NOT DECIDED | P2 | Repo split plan doesn't address frontend. Recommend in-repo for solo dev (like Paperless-ngx). |
| Decision: plugin system scope for V1 | NOT DECIDED | P2 | Full entry-point plugins vs. simple in-module registry. Recommend simple registry for V1. |

---

## P2 — Infrastructure

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Rotate weak DB passwords | Not started | P1 | Immich + Firefly postgres passwords. |
| SMTP for Authelia | Not started | P2 | Real SMTP relay instead of filesystem notifier. |
| Offsite backup (3-2-1) | Not started | P2 | Backblaze B2 or Wasabi target. |
| Repo split execution | Not started | P2 | Blocked on: module rename, personal data removal, frontend decision, CI strategy. Upgrade from P3 — blocks open-source release. |
| Jellyfin SSO | Not started | P3 | Wire Jellyfin to Authelia OIDC. |
| BIOS AC recovery | User action | P3 | Set "Power On" after AC loss on optiplex + miniserver. |

---

## P2 — Visual & Product Polish

| Task | Status | Priority | Detail |
|------|--------|----------|--------|
| Composer redesign | Not started | P2 | Premium, intentional design. |
| Status transitions | Not started | P2 | Subtle routing/thinking/streaming/done transitions. |
| Density toggle | Not started | P2 | Compact/comfortable display modes. |
| Production portrait assets | Not started | P2 | Per-agent portrait pack + responsive sizing + visual regression coverage. |
| Wire InlineDiffReviewCard | Not started | P2 | Live backend diff payloads, persist approve/reject/comment actions. |
| Claude runtime artifact browser | Not started | P3 | History/debug/notes with safe redaction and per-scope filtering. |
| Unified agent history surface | Not started | P3 | Sessions + run phases + tool/action events + runtime todos for per-agent forensic replay. |

---

## Architectural Risks (Monitor)

| Risk | Severity | Detail |
|------|----------|--------|
| Single-process bottleneck | Medium | Everything runs in one Python process. 4-agent parallel limit is appropriate, but SDK subprocess issues block the whole gateway. |
| Module-level mutable state | Medium | Most API routers use module-global variables set via `configure()`. Obsidian deduped to instance-based `ObsidianClient` (2026-03-07). Remaining: ha, paperless, firefly, email, drive still use module globals. Works for single-process, impossible for multi-worker. DI via FastAPI `Depends` would be more robust. |
| Import-time runtime construction | Medium | `build_runtime()` at module scope means importing `server.py` builds the world. Breaks `uvicorn --workers > 1` and makes testing harder. |
| Tight coupling to Claude Agent SDK | Medium | Entire dispatch assumes `ClaudeSDKClient`. Non-Claude backends get zero capabilities (tools, hooks, agents, MCP all stripped). |
| Frontend god-page growth | Medium | `+page.svelte` (717 lines) and `AgentWorkspaceShell` (810 lines) accumulate state. Every new feature increases coupling. |
| No rate limiting | Low | API has no rate limiting beyond break-glass lockout. Misbehaving client could flood gateway. |
| No structured logging | Low | Python `logging` with string formatting. Structured JSON logging would improve Loki integration. |

---

## Competitive Position Summary

| Dimension | vs. OpenClaw | vs. AutoGen/CrewAI/LangGraph |
|-----------|-------------|-------------------------------|
| Security | Stronger (zero-secret-exposure, SOPS+age, output sanitization) | Best-in-class (competitors have no built-in security model) |
| Testing | Stronger (1857 behavioral, no mocks) | Best-in-class (competitors use standard mock-based testing) |
| Observability | Stronger (self-hosted Alloy/Loki/Grafana) | Matches LangSmith (but self-hosted, not SaaS) |
| Memory | Comparable (Obsidian-as-truth vs. markdown files) | Stronger (hybrid FTS5 + Cognee vs. basic stores) |
| Distribution | Weaker (not packaged) | Weaker (competitors all on PyPI/npm) |
| CI/CD | Weaker (no CI pipeline) | Weaker (competitors all have GitHub Actions) |
| Documentation | Weaker (in-repo only) | Weaker (competitors all have docs sites) |
| Frontend | Comparable (SvelteKit vs. React) | Stronger (58 components vs. basic Studio UIs) |
| Config | Comparable (both YAML-driven) | Stronger (declarative YAML vs. programmatic) |
| Channel integrations | Weaker (single-chat-surface by design) | N/A (different scope) |

---

## Code-Level TODOs

| File | TODO | Priority |
|------|------|----------|
| `corvus/gateway/chat_session.py` | ~~Wire SDK confirm gate~~ — **DONE** (wired via `options.py` + `ConfirmQueue`) | ~~P0~~ |
| `corvus/api/schedules.py` | Add `Depends(get_user)` auth — **SECURITY** | P0 |
| `corvus/api/sessions.py:164` | Remove duplicate `GET /api/dispatch/active` route | P0 |
| `corvus/memory/hub.py:258` | MMR diversity re-ranking (config exists, not used) | P2 |
| `corvus/memory/hub.py:407` | `seed_context` calls `primary._list_sync` directly — breaks abstraction | P3 |
| `corvus/gateway/options.py:449` | Non-Claude backends stripped of all capabilities — architectural decision needed | P1 |
| `corvus/agents/hub.py:281` | Comment numbering in `_compose_prompt_layers` is wrong (duplicate "2", skips) | P3 |
| `corvus/config.py:39` | `ALLOWED_USERS = "patanet7"` hardcoded — needs env var or config | P1 |

---

## Current Test Suite

~1350 passing (non-live), 129 deselected (live), ~60 skipped. Full behavioral test coverage with no mocks. **No code coverage measurement.** All integration tests now have proper `@pytest.mark.integration` / `@pytest.mark.live` markers for selective execution.

---

## Decision Log

| Decision | Status | Options | Recommendation |
|----------|--------|---------|----------------|
| Session persistence model | UNDECIDED | A: Full transcript rows in `session_messages` / B: Compact event stream rendered to transcript | Decide before data model freezes |
| Plugin system scope for V1 | UNDECIDED | A: Full entry-point discovery (pip-installable) / B: Simple in-module registry | B for V1, A when community demands |
| Frontend repo placement | UNDECIDED | A: In-repo (monorepo like Paperless-ngx) / B: Separate repo (like Home Assistant) | A for solo dev |
| Module rename timing | UNDECIDED | A: Rename before split / B: Rename + split atomically | A — rename is mechanical, split is strategic |
| Non-Claude capability strategy | UNDECIDED | A: Implement OpenAI-compat tool calling / B: Accept chat-only for non-Claude / C: Proxy through Claude-format adapter | A long-term, B acceptable for V1 |
