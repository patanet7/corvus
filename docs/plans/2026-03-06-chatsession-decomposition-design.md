# ChatSession Decomposition + P0 Correctness + Testing Design

**Goal:** Decompose the 1,443-line ChatSession monolith into focused modules, wire up remaining frontend gaps, and add testing/quality gates.

**Approach:** Three phases — decomposition first (unblocks everything), P0 correctness second (functional gaps), testing third (confidence).

---

## Phase 1: ChatSession Decomposition + Frontend Wire-Up

### Current State

`corvus/gateway/chat_session.py` — 1,443 lines, single class doing:
- WebSocket send/persist/trace (lines 189-317)
- Payload builders and run lifecycle helpers (lines 319-554)
- SDK client lifecycle + streaming (lines 560-1018, `execute_agent_run` = 459 lines)
- Dispatch control listener (lines 1024-1089)
- Dispatch orchestration (lines 1125-1320, 196 lines)
- WebSocket main loop (lines 1326-1443)

### Target Modules

#### `corvus/gateway/session_emitter.py` (~150 lines)

`SessionEmitter` class — all send/persist/trace methods:
- `_ws_send()`, `_persist_session_event()`, `_persist_run_event()`
- `_publish_trace()`, `send()` (unified orchestrator)
- `_base_payload()`, `_emit_phase()`
- `_emit_run_failure()`, `_emit_run_interrupted()`

Constructor takes: `runtime`, `websocket`, `session_id`, `send_lock`, `transcript`

#### `corvus/gateway/run_executor.py` (~250 lines)

Extracts `execute_agent_run()`:
- Backend/model resolution
- Run row persistence + event emissions
- SDK client lifecycle (`async with ClaudeSDKClient`)
- Streaming loop (AssistantMessage + ResultMessage)
- Phase emissions (routing → planning → executing → compacting)
- Success/failure/interrupt result construction

Receives `SessionEmitter` + runtime dependencies, not the full ChatSession.

#### `corvus/gateway/dispatch_orchestrator.py` (~200 lines)

Extracts `_execute_dispatch_lifecycle()` + `dispatch_control_listener()`:
- Dispatch row persistence and events
- TurnContext construction
- Concurrent control listener + run execution
- Dispatch summary and completion

#### `corvus/gateway/chat_session.py` (~200 lines, down from 1,443)

Thin coordinator:
- `__init__` — constructs `SessionEmitter`, `ConfirmQueue`
- `run()` — WebSocket main loop (init message, message routing)
- `_degraded_message_loop()`
- Delegates to `DispatchOrchestrator` and `RunExecutor`

#### `corvus/gateway/protocol.py` (new)

Typed event definitions for every WS message type the backend emits. Serves as single source of truth for the protocol contract. Frontend types generated/synced from this.

### Frontend Wire-Up (Phase 1)

**Protocol type centralization:**
- Create `frontend/src/lib/protocol.ts` — typed discriminated unions for all WS message types
- Replace inline `msg.type === "..."` checks with typed handlers
- Synced with `corvus/gateway/protocol.py`

**Task dispatch completion (master TODO Step 7):**
- Ensure `task_start`, `task_progress`, `task_complete` events are consistently emitted
- Wire `TaskSidebar` to correct task lifecycle events
- Task replay against persisted run events

**Agent History surface:**
- Backend: `GET /api/agents/{id}/history` — sessions + runs + tool events per agent
- Frontend: Wire `AgentWorkspaceShell` history tab to this endpoint

---

## Phase 2: P0 Correctness Gaps

### Model contract tests
- Backend: prove `resolve_backend_and_model()` output is passed to `ClaudeSDKClient`
- Frontend: prove model selector selection reaches backend via WS `model` field

### Backend data model decision
- Keep both `session_messages` (transcript rows) and `run_events` (event stream)
- Messages for quick transcript display, events for forensic replay
- Document the contract — no schema change needed

### Fallback ladder UX
- Backend: `GET /api/agents/{id}/model-config` — agent's model routing config
- Frontend: Wire `AgentModelRoutingCard` to real endpoint

---

## Phase 3: Testing & Quality Gates

- **Protocol parsing tests** — unit tests for shared protocol types (Python + TS)
- **SQLite integration tests** — real DB, seed sessions/runs/events, query, verify
- **E2E policy enforcement** — Playwright: trigger confirm-gated tool, verify dialog, approve, verify execution
- **E2E model selection** — Playwright: select model, send message, verify `run_start` shows selected model

---

## Delivery Summary

| Phase | Backend | Frontend | Tests |
|-------|---------|----------|-------|
| 1: Decompose | 4 new modules, ChatSession → coordinator | Protocol types, task dispatch, agent history | Unit tests per module |
| 2: P0 Correctness | Agent history endpoint, model config endpoint | Model routing card wire-up | Model contract tests |
| 3: Testing | — | — | SQLite integration, E2E policy, E2E model |
