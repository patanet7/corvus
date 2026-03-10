---
title: "Corvus Chat Protocol Contract v1"
type: spec
status: implemented
date: 2026-03-03
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Corvus Chat Protocol Contract v1 (Frontend + Backend Shared)

> Date: 2026-03-03
> Purpose: Shared, implementation-neutral contract for WebSocket and REST payloads used by the SvelteKit chat surfaces.
> Scope: Router/direct/parallel dispatch, run lifecycle phases, replay endpoints, compatibility events.

## WebSocket Client -> Server (`chat`)

```json
{
  "type": "chat",
  "message": "string",
  "model": "optional model id",
  "target_agent": "optional single agent",
  "target_agents": ["optional multi-target list", "@all supported"],
  "dispatch_mode": "router|direct|parallel",
  "requires_tools": false
}
```

Resolution rules:
- `target_agents` (if present) wins over `target_agent`
- `@all` expands to all enabled agents
- `dispatch_mode=router` allows backend routing; `direct` pins one recipient; `parallel` fans out

## WebSocket Server -> Client Lifecycle

Required lifecycle events:
- `dispatch_start`
- `dispatch_plan`
- `run_start` (per targeted agent)
- `run_phase` with deterministic phases:
  - `queued -> routing -> planning -> executing -> compacting -> done|error`
- `run_output_chunk` (ordered with `chunk_index`, includes `final=true` marker)
- `run_complete`
- `dispatch_complete`

Backward-compatible task events (still emitted):
- `task_start`
- `task_progress`
- `task_complete`

Tool/confirm events remain:
- `tool_start`
- `tool_result`
- `confirm_request`
- `confirm_response`

## Run Output Streaming Guarantees

Per run:
- `chunk_index` strictly increases from `0`
- exactly one `run_output_chunk` with `final=true`
- `run_complete` only after final chunk
- `dispatch_complete` only after all `run_complete` events

## REST Endpoints for Replay and Agent Surfaces

- `GET /api/agents`
  - enriched agent rows (`runtime_status`, `current_model`, `queue_depth`)
- `GET /api/agents/{agent}/sessions`
- `GET /api/agents/{agent}/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `GET /api/dispatch/{dispatch_id}`
- `GET /api/dispatch/{dispatch_id}/runs`
- `GET /api/dispatch/{dispatch_id}/events`

Session replay compatibility:
- `GET /api/sessions/{id}/events` includes task/run/dispatch events for timeline reconstruction.

## Frontend Mapping Notes

- `run_start` should create/update task cards (task id fallback: run id).
- `dispatch_plan` should render hierarchical routes (subtask id, skill lane, model assignment) before execution starts.
- `run_phase` drives phase stepper and status state.
- `run_output_chunk` updates stream previews/log rows.
- `run_complete` finalizes task card result + cost.
- `dispatch_complete` sets turn-level completion state.

## Non-goals in v1

- No UI-prescribed rendering styles in this contract.
- No backend implementation details (threading model, SDK lifecycle) in this contract.
- No hardcoded fallback model policy in backend; frontend decides fallback strategy.
