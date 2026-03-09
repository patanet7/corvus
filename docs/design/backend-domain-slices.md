# Backend Domain Slices (Clean Architecture Target)

Date: 2026-03-03
Owner: backend
Status: active

## Goal

Keep backend modules small, DRY, and behavior-first by organizing around stable domains rather than endpoint type or legacy file history.

## Core domain boundaries

1. `agents`
- Owns agent definitions, model strategy, routing hints, and lifecycle metadata.
- Source of truth for agent capabilities and domain isolation rules.

2. `memory`
- Owns memory write/read/search policies, retention, and domain visibility.
- Exposes ingestion/retrieval contracts only; storage backend details stay internal.

3. `capabilities`
- Owns tool module registry, policy checks, secret-safe execution, and module health.
- No agent/session orchestration logic in this domain.

4. `dispatch`
- Owns planner output execution, run graph lifecycle, and bounded fan-out.
- Shared by WebSocket chat, webhooks, and scheduler triggers.

5. `sessions`
- Owns persisted session/dispatch/run entities and replay event streams.
- Pure persistence + query interfaces; no transport concerns.

6. `control`
- Owns interrupts, break-glass session scope, and active-run control plane.
- Must be transport-agnostic so HTTP/WS use identical semantics.

7. `api`
- Thin transport adapters only (validation + auth + mapping to domain services).
- No business orchestration beyond request mapping.

## Target package shape

```text
corvus/
  api/
    chat.py
    sessions.py
    schedules.py
    webhooks.py
    agents.py
    control.py
  gateway/
    runtime.py
    options.py
    task_planner.py
    background_dispatch.py
    control_plane.py
  agents/
    hub.py
    registry.py
    spec.py
  memory/
    hub.py
    config.py
    backends/
  capabilities/
    registry.py
    modules.py
    config.py
  session_manager.py
```

## Current cleanup status

- Completed: shared non-WS planner execution extracted to `corvus/gateway/background_dispatch.py` and reused by webhook/scheduler paths.
- Completed: static route guard for `/api/dispatch/active` added to avoid dynamic route shadowing.
- Completed: `SessionManager` decomposed into domain repositories in `corvus/sessions/` with facade compatibility preserved.
- Completed: user-scoped `SessionService` added (`corvus/sessions/service.py`) and wired into `corvus/api/sessions.py`.
- Completed: shared dispatch aggregation helpers added in `corvus/gateway/dispatch_metrics.py` for chat + webhook/scheduler parity.
- Completed: shared dispatch runtime execution extracted to `corvus/gateway/dispatch_runtime.py` and reused by chat + background dispatch.
- Completed: `AgentsService` added (`corvus/agents/service.py`) and wired into `corvus/api/agents.py`.
- Remaining: split per-run execution and control listener concerns from `corvus/api/chat.py` into smaller dispatch runtime collaborators.

## Next refactor order (impact-first)

1. `dispatch` service extraction from `corvus/api/chat.py`
- Extract per-run lifecycle engine and control-listener protocol into dedicated dispatch collaborators.
- Keep API file focused on socket protocol + auth + thin message mapping.

2. `sessions` facade trim and app service wiring
- Keep `SessionManager` as compatibility facade while routing app code to repository services directly where appropriate.
- Add `SessionService` for transport-agnostic orchestration (pagination guards, user scoping helpers, replay composition).

3. `agents` application service
- Keep `hub.py` focused on static/dynamic agent composition.
- Continue moving agent-session/run filtering logic out of API transport handlers.

4. `memory` application service
- Add `corvus/memory/service.py` for write/search/query policies.
- Keep backend adapters (`fts5`, overlays) isolated in `memory/backends`.

## Guardrails

- No mocks in tests.
- Every extracted service must keep existing endpoint contracts unchanged.
- Add regression tests for every route conflict or replay contract discovered during manual checks.
