# Backend Modularization Completion (Phase: Server Decomposition)

Date: 2026-03-03

## Scope Completed

This pass completed the server decomposition work described in:
- `docs/plans/2026-03-01-corvus-hub-architecture-design.md` (Section 8: server cleanup)
- `docs/plans/2026-03-02-legacy-removal-plan.md` (Sub-phase D direction)

### 1. `server.py` reduced to composition root

`corvus/server.py` now primarily handles:
- environment bootstrap (`load_dotenv` + CLAUDECODE unset)
- runtime construction (`build_runtime()`)
- lifespan orchestration (supervisor + scheduler)
- router registration
- compatibility exports (`build_options`, `_init_credentials`, `_any_llm_configured`, `session_mgr`, `emitter`)

### 2. Runtime wiring extracted

New module: `corvus/gateway/runtime.py`
- central runtime assembly (`GatewayRuntime`, `build_runtime`)
- credentials injection + dynamic sanitize pattern registration
- AgentsHub/CapabilitiesRegistry/MemoryHub setup and validation
- RouterAgent Ollama fallback setup

### 3. Option/model resolution extracted

New module: `corvus/gateway/options.py`
- hook assembly (`build_hooks`)
- ClaudeAgentOptions assembly (`build_options`, `build_backend_options`)
- backend/model selection helpers (`resolve_backend_and_model`, `ui_model_id`)
- backend availability guard (`any_llm_configured`)

### 4. API routes split by bounded context

New modules:
- `corvus/api/chat.py` — WebSocket chat lifecycle
- `corvus/api/models.py` — model list/refresh
- `corvus/api/schedules.py` — schedule list/update/trigger
- `corvus/api/sessions.py` — session CRUD/export/messages
- `corvus/api/webhooks.py` — webhook auth + typed dispatch

### 5. Scheduler resilience improvements

- `corvus/scheduler.py` now records cancelled runs as `status=error` instead of dropping audit rows.
- APScheduler jobs allow limited overlap (`max_instances=3`) so rapid manual/forced runs are tracked.
- `corvus/webhooks.py` dispatch now fails fast when no LLM backend is configured and handles cancelled dispatch cleanly.

### 6. Frontend/backend contract coverage added

New behavioral tests:
- `tests/gateway/test_frontend_backend_contracts.py`
  - `/api/models` response shape used by frontend `ModelInfo`
  - `/api/sessions` and `/api/sessions/{id}/messages` shapes used by frontend API mappers
  - WebSocket `init` contract and ping/pong contract

### 7. Existing tests realigned to new module boundaries

Source-contract checks that previously hardcoded `server.py` internals were updated to validate the new files where behavior now lives.

## Validation Results

- `mise run test:gateway` -> passing (`846 passed, 9 skipped`)
- `mise run test:frontend:check:log` -> passing
- `mise run test:frontend:unit:log` -> passing
- `mise run test:frontend:e2e:log` -> passing after Playwright web server stabilization in `frontend/playwright.config.ts`

## Notes

- A full repository lint pass still reports pre-existing unrelated issues in `tests/integration/test_memory_integration.py` (unused imports).
- This pass focused on backend modularity, runtime composition, and frontend-facing API/WS contracts.
