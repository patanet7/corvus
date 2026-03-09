# Corvus Agent Surfaces + Multi-Agent Messaging Plan

> Date: 2026-03-03
> Goal: Make agents first-class surfaces (not just router targets), enable direct and multi-agent messaging, and support full execution-phase visibility (including compacting) with replayable history.
> Inputs: stitch (1), stitch (2), stitch (3)

## Product Direction (from stitch references)

- `stitch (2)` pattern: agent directory + agent configuration workspace + validation rail.
- `stitch (3)` pattern: task dispatch board with per-agent cards, logs, progress, interrupts.
- `stitch (1)` pattern: policy/guardrail visibility + live decision feed.

Translate these into Corvus as three coordinated surfaces:

1. Agent Hub (directory + status + quick actions)
2. Agent Workspace (chat/tasks/config/validation per selected agent)
3. Dispatch Board (parallel work supervision and control)

## Component Breakdown (Frontend)

### 1) Agent Navigation Layer

- `AgentDirectorySidebar`
  - Search/filter agents
  - Status chips (`active`, `busy`, `offline`, `degraded`)
  - Quick actions: `Open Chat`, `Dispatch Task`, `Configure`
- `AgentListItem`
  - Portrait, name, domain, health dot, current model badge
- `AgentPresenceBadge`
  - Last heartbeat age + current phase

### 2) Agent Workspace Shell

- `AgentWorkspaceShell`
  - Tabs: `Chat`, `Tasks`, `Config`, `Validation`
  - Binds selected agent context globally
- `AgentChatPane`
  - Agent-pinned chat timeline (isolated from global router stream)
  - Agent-specific session selector
- `AgentTaskPane`
  - Task cards scoped to selected agent
  - Tool log strip + interrupt/resume controls

### 3) Multi-Agent Compose & Dispatch

- `RecipientPicker`
  - Single-select and multi-select agents
  - Supports `@agent`, `@all`, and saved groups (`@ops`, `@personal-stack`)
- `DispatchModeToggle`
  - `Direct` (single agent)
  - `Parallel` (fan-out to many)
  - `Router` (existing auto route)
- `DispatchPlanPreview`
  - Shows which agents will run, model assignment per agent, estimated cost/context

### 4) Execution Timeline Components

- `DispatchTimeline`
  - Parent dispatch event + child per-agent runs
- `RunPhaseStepper`
  - Phases: `queued -> routing -> planning -> executing -> compacting -> done/error`
- `ToolFeedInline`
  - Structured tool events under each run
- `RunOutputStream`
  - Live streamed chunks grouped by agent/turn

### 5) Agent Config + Validation UI

- `AgentConfigForm`
  - Persona, model strategy, skill matrix, connection policy
- `ModelRoutingMatrix`
  - `reasoning`, `code`, `rapid` profile mapping per agent
- `ServiceConnectionsPanel`
  - Connection health + reauth + quota
- `ValidationRail`
  - Runtime checks, dependency checks, quota warnings, policy violations

## Backend Support Required

### A) APIs (REST)

- `GET /api/agents` (enriched)
  - include: runtime status, current model, tool capability, last heartbeat, queue depth
- `GET /api/agents/{id}/sessions`
  - agent-scoped session history
- `GET /api/agents/{id}/runs?status=...`
  - active/completed runs for selected agent
- `GET /api/runs/{run_id}`
  - full run detail with phases, tools, output refs
- `POST /api/dispatch`
  - create multi-agent dispatch from one user prompt

### B) WebSocket Protocol Extensions

- Extend client `chat` message:
  - `target_agent?: string` (existing)
  - `target_agents?: string[]` (new)
  - `dispatch_mode?: 'router' | 'direct' | 'parallel'`
- New server messages:
  - `dispatch_start`
  - `run_start` (per agent)
  - `run_phase` (includes `phase` + summary)
  - `run_output_chunk` (stream chunk per agent run)
  - `run_complete`
  - `dispatch_complete`

### C) Execution + Persistence Model

- Persist dispatch graph:
  - `dispatches` table (one user request)
  - `agent_runs` table (one per targeted agent)
  - `run_events` table (phase/tool/output events)
- Keep session linkage:
  - each run linked to `session_id` and `turn_id`
- Replay endpoints:
  - `GET /api/sessions/{id}/events` (existing)
  - `GET /api/dispatch/{id}/events` (new)

### D) Phase Engine (important for “compacting”)

- Server emits deterministic run phases:
  - `queued`
  - `routing`
  - `planning`
  - `executing`
  - `compacting`
  - `done` / `error` / `interrupted`
- `compacting` fired when model output is being merged/summarized/finalized before completion.

### E) Streaming Guarantees

- Emit ordered stream chunks with sequence numbers per run:
  - `{ run_id, chunk_index, content, final=false }`
- Emit explicit final marker:
  - `{ run_id, final=true, tokens_used, cost_usd }`
- Frontend groups by `run_id` and supports partial render with rollback on reconnect.

## Acceptance Criteria

- User can open any agent and chat directly without going through router-only flow.
- User can send one prompt to multiple agents in parallel and observe each run independently.
- Task cards populate in real time and replay correctly from persisted events.
- Phase bar visibly includes `compacting` before final completion when applicable.
- Streaming output is incremental, ordered, and attributed to the correct agent run.

## Implementation Order

1. Enriched agent registry API + `AgentDirectorySidebar`.
2. Agent-scoped sessions and `AgentWorkspaceShell` with `Chat` tab.
3. Dispatch API + WS protocol (`target_agents`, run events).
4. Persist dispatch/run/event tables + replay endpoints.
5. Phase engine with explicit `compacting` event.
6. Streaming contract hardening (chunk ordering/final markers).
7. Validation rail + config matrix UI from stitch (2) patterns.
8. E2E coverage: direct agent chat, parallel dispatch, replay, compacting phase, reconnect streaming.
