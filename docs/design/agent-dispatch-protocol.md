# Agent Dispatch Protocol (Backend Contract)

Date: 2026-03-03
Owner: backend
Status: active

This document is the shared contract for backend/frontend integration around
agent dispatch, run lifecycle, and replay APIs.

## Dispatch Modes

- `router`: backend chooses agent(s) from user message
- `direct`: use explicit `target_agent`
- `parallel`: fan out to `target_agents[]`

Valid values: `router | direct | parallel`

## WebSocket Client Message

```json
{
  "type": "chat",
  "message": "string",
  "model": "optional model id",
  "target_agent": "optional single agent",
  "target_agents": ["optional", "multi", "agent", "list"],
  "dispatch_mode": "router|direct|parallel",
  "requires_tools": false
}
```

## WebSocket Server Lifecycle Messages

### Dispatch

- `dispatch_start`
- `dispatch_plan`
- `dispatch_complete`
- `interrupt_ack` (when user sends `{"type":"interrupt"}`)

Payload fields:
- `dispatch_id`
- `session_id`
- `turn_id`
- `dispatch_mode`
- `target_agents`
- `max_parallel` (from backend bound `MAX_PARALLEL_AGENT_RUNS`, included on `dispatch_complete`)
- `interrupted_count` (included on `dispatch_complete`)
- `task_type` / `decomposed` / `strategy` (included on `dispatch_complete`)

`dispatch_plan` payload additionally includes:
- `task_type`
- `decomposed`
- `strategy`
- `rationale`
- `routes[]` with per-route metadata (`agent`, `task_type`, `subtask_id`, `skill`, `instruction`, `requested_model`, `prompt_preview`)

### Run

- `run_start`
- `run_phase`
- `run_output_chunk`
- `run_complete`

Common payload fields:
- `dispatch_id`
- `run_id`
- `session_id`
- `turn_id`
- `agent`
- `task_type` (planner task class)
- `subtask_id` (route-local subtask identifier)
- `skill` (model-router skill lane)
- `instruction` (route instruction text from task routing config)
- `route_index` (0-based execution order in dispatch plan)

### Run phases

Ordered states:
- `queued`
- `routing`
- `planning`
- `executing`
- `compacting`
- terminal: `done | error | interrupted`

### Streaming guarantees

`run_output_chunk` includes:
- `chunk_index` (monotonic per run)
- `content`
- `final` (boolean)

Final chunk (`final=true`) includes:
- `tokens_used`
- `cost_usd`
- `context_limit`
- `context_pct`

## Dispatch-time control messages

While a dispatch is active, backend consumes control messages on the same socket:

- `{"type":"interrupt"}` -> backend sets dispatch interruption, emits `interrupt_ack`,
  marks affected runs `interrupted`, and emits `dispatch_complete` with `status=interrupted`.
- `{"type":"ping"}` -> `{"type":"pong"}`
- `{"type":"confirm_response", ...}` -> echoed/persisted as `confirm_response`
- New chat prompts received while dispatch is running return typed error:
  `{"type":"error","error":"dispatch_in_progress",...}`

## REST Endpoints

### Sessions

- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/messages`
- `GET /api/sessions/{session_id}/events`
- `PATCH /api/sessions/{session_id}`
- `DELETE /api/sessions/{session_id}`

### Agent surfaces

- `GET /api/agents`
- `GET /api/agents/{name}`
- `GET /api/agents/{name}/sessions`
- `GET /api/agents/{name}/runs`

### Dispatch CRUD

- `POST /api/dispatch`
- `GET /api/dispatch`
- `GET /api/dispatch/{dispatch_id}`
- `PATCH /api/dispatch/{dispatch_id}`
- `DELETE /api/dispatch/{dispatch_id}`
- `GET /api/dispatch/{dispatch_id}/runs`
- `GET /api/dispatch/{dispatch_id}/events`
- `POST /api/dispatch/{dispatch_id}/interrupt`
- `GET /api/dispatch/active`

### Run CRUD

- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `PATCH /api/runs/{run_id}`
- `DELETE /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `POST /api/runs/{run_id}/interrupt`

### Break-glass control

- `POST /api/break-glass/activate`
- `POST /api/break-glass/deactivate`
- `GET /api/break-glass/status?session_id=...`

## Persistence Model

- `dispatches` table: one user prompt dispatch
- `agent_runs` table: one row per targeted agent run
- `run_events` table: replayable run lifecycle/tool/output events

## Status enums

### Dispatch status

- `queued`
- `running`
- `done`
- `error`
- `interrupted`
- `cancelled`

### Run status

- `queued`
- `routing`
- `planning`
- `executing`
- `compacting`
- `done`
- `error`
- `interrupted`
