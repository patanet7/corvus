# Corvus Chat UI Master TODO (SvelteKit + Claude SDK)

> Date: 2026-03-03
> Scope: Chat UX parity with best-in-class tooling, explicit agent control, multi-session history, model correctness, DRY architecture, repeatable tests.

## Ground Rules

- [ ] Keep one source of truth per concern (protocol, agent specs, model config, theme tokens).
- [ ] No mock-based tests for backend behavior paths.
- [ ] Every feature ships with contract tests and at least one end-to-end test.
- [x] Frontend state orchestration lives in stores/services, not page components.
- [x] Use `mise run` tasks where available, and write all test run logs to `tests/output/`.

## Confirmed Current Gaps

- [x] `config/agents/huginn.yaml` is missing, so registry cannot load Huginn as a first-class agent.
- [x] Per-message model override from UI is not honored by SDK call path (`ClaudeSDKClient.query()` has no model argument).
- [x] Session list/history UX is incomplete on frontend.
- [ ] Tasks mode has partial wiring but still lacks full backend event flow.
- [x] `@agent` targeting is not implemented.
- [x] Slash commands and skill passthrough are not implemented.
- [x] Model dropdown UX is poor (direction, discoverability, state clarity).
- [x] Chat runtime state can remain in `streaming/queued` visual mode after assistant text renders in live browser flow.
- [x] Chat transcript can collapse the immediately previous user turn (`Load 1 older message`) during short live sessions.

## P0: Correctness First

- [x] Create `config/agents/huginn.yaml` and wire it to the existing Huginn prompt file.
- [x] Ensure `/ws init` payload default agent reflects registry config, not hardcoded fallback.
- [x] Define model override behavior contract:
- [x] `default`: use agent preferred model from YAML/router.
- [x] `manual`: if user picks model, backend uses it for that turn.
- [x] `reset`: user can return to preferred model quickly.
- [x] Refactor backend chat execution so model selection is actually honored with Claude SDK constraints.
- [ ] Add backend and frontend contract tests proving selected model is used.
- [x] Add explicit error path when selected model is unavailable, with UI feedback.
- [x] Runtime backend isolation: maintain SDK clients per backend so env overrides actually apply.
- [x] Filter non-chat Ollama entries (e.g. embeddings) from model selector payload.
- [x] Move fallback model choice to frontend state/orchestrator (backend returns errors, UI decides next model).
- [x] Add backend capability metadata (tool-call support, streaming support) and enforce in both API and UI.
- [x] Add fallback behavior when a selected model cannot execute tool-enabled prompts (auto-switch to chat-safe profile or block with actionable UI).
- [ ] Guarantee manual model dispatch remains available from every send surface (global chat, agent workspace, slash command path) even when fallbacks engage.
- [ ] Add frontend-editable fallback ladders per agent lane (reasoning/code/rapid) with persisted ordering and enable/disable controls.
- [x] Replace static SDK permission bypass with dynamic per-agent permission mode + SDK `can_use_tool` gating wired to capabilities registry/env/health checks.
- [x] Isolate SDK run working directories per session+agent (dedicated workspace/worktree root) so agent tool runs cannot mutate the active developer checkout by default.
- [x] Isolate Claude CLI home/state per deployment (`CORVUS_CLAUDE_HOME`) so SDK sessions do not write global user `~/.claude` artifacts.
- [x] Explicitly set `CLAUDE_CONFIG_DIR` into deployment-local runtime home and seed config (`.claude/.claude.json`) to eliminate first-run CLI warning noise.
- [x] Live-verified websocket turn on `PORT=18791`: session artifacts land under `.data/claude-home/.claude/*` and repo-local `.claude/` remains untouched.
- [x] Regression suite re-run after isolation work: `1029 passed, 9 skipped` (`tests/output/test-gateway-20260304-071003.log`).
- [x] Scope Claude runtime state per user+agent by default (`CORVUS_CLAUDE_HOME_SCOPE=per_agent`) so agents do not share local `.claude` history/todo/debug artifacts.
- [x] Add optional strict scope (`CORVUS_CLAUDE_HOME_SCOPE=per_session_agent`) for fully isolated per-session agent state.
- [x] Add default Claude runtime config template (`config/claude-runtime/claude.json`, override via `CORVUS_CLAUDE_CONFIG_TEMPLATE`) copied into each scoped home on first use.
- [x] Live-verified two-agent isolation (`general`, `work`) writes to separate homes under `.data/claude-home/users/patanet7/agents/*` with no new global `~/.claude` writes in that run.
- [x] Regression suite re-run after scope change: `1033 passed, 9 skipped` (`tests/output/test-gateway-20260304-071741.log`).

## P0: Multi-Chat and Session History

- [ ] Backend data model decision:
- [ ] Option A: Persist full transcript rows in `session_messages`.
- [ ] Option B: Persist compact event stream and render to transcript.
- [x] Implement session message persistence in websocket loop for user and assistant messages.
- [x] Persist tool start/result and confirm events for replay.
- [x] Add API endpoints:
- [x] `GET /api/sessions` list with paging.
- [x] `GET /api/sessions/{id}` metadata.
- [x] `GET /api/sessions/{id}/messages` transcript payload.
- [x] `PATCH /api/sessions/{id}` rename.
- [x] `DELETE /api/sessions/{id}` delete.
- [x] Frontend: load sessions on mount and render real sidebar data.
- [x] Frontend: selecting a session hydrates `currentSession.messages`.
- [x] Frontend: new chat creates isolated local state and server session binding.
- [x] Frontend: add empty, loading, and error states for session history panel.
- [ ] Add unified Agent History surface (sessions + run phases + tool/action events + runtime todos) for per-agent forensic replay.

## P0: Memory Workspace + Dispatch Control Parity

- [x] Add authenticated backend memory REST surface (`/api/memory/agents`, list/search/get/create/forget records).
- [x] Add backend behavioral tests for memory endpoints (auth, isolation, permissions).
- [x] Add additive migration guard for legacy memory SQLite schemas so new memory REST writes don’t fail on existing deployments.
- [x] Add frontend memory API client layer and control-plane dispatch API client layer.
- [x] Add frontend memory backend status API mapping (`/api/memory/backends`) with typed overlay health/config contracts.
- [x] Enable Memory mode in `ModeRail` and mount `MemoryPanel` in the main route.
- [x] Add memory workspace UI flows: agent context selection, create/search/filter/inspect/forget records.
- [x] Complete memory CRUD by adding record update API + UI edit flow (`PATCH /api/memory/records/{id}`).
- [x] Decompose memory workspace into reusable cards (`MemoryAgentContextCard`, `MemoryBackendStatusCard`, `MemoryCreateCard`) for DRY composition.
- [x] Expose active dispatch list + interrupt action inside memory workspace.
- [x] Add static Playwright coverage for enabled Memory mode navigation/rendering.
- [x] Add live Playwright coverage for memory record CRUD (create/update/search/forget) against real backend APIs.

## P0: Explicit Agent Targeting via `@`

- [x] Composer parser for prefix mention (`@homelab restart plex`).
- [x] Mention autocomplete menu from active agent registry payload.
- [x] WS payload extension: include optional `target_agent`.
- [x] Backend behavior:
- [x] If `target_agent` present and valid, bypass router.
- [x] If invalid, return typed error and do not silently reroute.
- [x] UI indicator that turn is pinned to explicit agent.
- [x] Add remove-pin action to return to automatic routing.
- [x] Tests for parser edge cases (`@`, `@unknown`, escaped `@@`, multiline).

## P0: Model Selector UX Rewrite

- [x] Replace current dropdown with robust popover that collision-flips (opens up when near bottom).
- [x] Add searchable command-palette style model picker.
- [x] Group by backend and show availability/status badges.
- [x] Show active mode label: `Preferred`, `Manual override`, or `Unavailable`.
- [x] Add one-click `Use preferred model` reset control.
- [x] Persist model preference per agent in local storage.
- [x] Keyboard support: arrow nav, enter select, escape close.

## P1: Claude Code-Like Controls (System-Specific)

- [x] Slash command parser in composer.
- [x] Initial commands:
- [x] `/agent <name>` set active explicit agent.
- [x] `/model <id>` set manual model override.
- [x] `/new` new chat.
- [x] `/clear` clear current transcript.
- [x] `/sessions` quick-open session history.
- [x] `/help` discoverable command list.
- [x] Skills passthrough command design (`/skill <name> ...`) with backend validation.
- [x] Add command suggestion UI as user types `/`.
- [x] `/dispatch <router|direct|parallel>` quick mode switching.
- [x] Keep `@` and `/` suggestion overlays vertically stacked above the composer input (Claude/Codex-style placement).

## P1: Task/Dispatch UX Completion

- [x] Ensure backend emits `task_start`, `task_progress`, `task_complete` during multi-agent dispatch.
- [x] Persist task stream events for replay.
- [x] Link tasks to originating chat turn and session ID.
- [x] Link tool calls to task trace IDs (`call_id`) and support jump from chat tool card to trace view.
- [x] Task details panel in Tasks mode (summary, logs, tools, cost).
- [x] Agent-scoped interrupt action from task card.
- [x] Completed task archive with filter controls.
- [ ] Add supervisor queue UX for long-running/background dispatches (pause/resume, reassignment, stale-run triage).

## P0: Full Agent Trace Observability

- [x] Add durable `trace_events` persistence with hook-style event shape (`source_app`, `hook_event_type`, payload, summary, model, timestamp).
- [x] Capture trace rows from live websocket chat flow and publish to a dedicated in-memory trace hub.
- [x] Add trace REST surface:
- [x] `GET /api/traces/recent`
- [x] `GET /api/traces/filter-options`
- [x] `GET /api/traces/{id}`
- [x] `GET /api/sessions/{id}/traces`
- [x] Add live trace stream websocket (`/ws/traces`) for timeline dashboards.
- [x] Enable Timeline mode in frontend and render a dedicated trace panel with filter chips, search, payload drill-down, and live connection state.
- [x] Add backend behavioral tests for trace repositories and trace API endpoints.
- [x] Add frontend e2e coverage for live trace stream updates and filter interactions.

## P0: Agent Surfaces (Direct + Multi-Agent)

- [x] Build `AgentDirectorySidebar` (search, status chips, quick actions) so agents are first-class navigation targets.
- [x] Build `AgentWorkspaceShell` with tabs: `Chat`, `Tasks`, `Config`, `Validation`.
- [x] Add agent workspace run replay timeline (filterable run events with payload drill-down).
- [x] Add reusable agent specialty component (complexity, memory domain, tool modules, prompt status) and render it in directory/workspace/chat header views.
- [x] Add agent-scoped chat sessions (`GET /api/agents/{id}/sessions`) and UI filtering.
- [x] Add recipient picker supporting single, multi-select, and `@all` group semantics.
- [x] Extend WS protocol for multi-target dispatch (`target_agents[]`, `dispatch_mode`).
- [x] Add backend dispatch lifecycle events: `dispatch_start`, `run_start`, `run_phase`, `run_output_chunk`, `run_complete`, `dispatch_complete`.
- [x] Persist dispatch graph (`dispatches`, `agent_runs`, `run_events`) and expose replay endpoints.
- [x] Add explicit run phase state machine including `compacting` before completion.
- [x] Add ordered streaming guarantees per run (`chunk_index`, final markers, reconnect safety).
- [x] Stabilize replay hydration and live task trace rendering with per-run chunk ordering, dedupe, and missing-range notices.
- [x] Add E2E coverage for direct-agent chat and compacting phase persistence/visibility (live backend flow).
- [x] Add E2E coverage for direct-agent chat, multi-agent dispatch, replay restore, and compacting phase visualization.

## P0: Backend-Driven Agent Cards (Identity, Prompt, Tools, Connections, Permissions)

- [x] Add frontend contract mapping for `/api/agents/{id}` profile payload (models, prompt_file, tools, memory, metadata).
- [x] Implement composed config cards in agent workspace:
- [x] `AgentIdentityCard`
- [x] `AgentPromptIdentityCard` (soul/prompt/model routing summary)
- [x] `AgentToolsPermissionsCard` (builtin tools + confirm-gated permissions + modules)
- [x] `AgentConnectionsCard` (module connection state + memory read/write gates)
- [x] Hydrate selected agent profile from backend and pass through workspace shell.
- [x] Wire connection state from backend capability health endpoint (`/api/capabilities/{name}`) into connection cards.
- [ ] Add explicit backend fields for external connection health (per module) and wire card state from real health, not runtime fallback.
- [x] Add prompt preview endpoint with safe redaction and render expandable prompt inspector.
- [x] Add per-agent permission matrix card (allow/deny/confirm) once backend exposes normalized policy schema.
- [x] Add per-agent Claude runtime todo artifacts endpoint (`GET /api/agents/{id}/todos`) scoped by authenticated user + configured Claude home scope.
- [x] Add Agent Workspace runtime todos panel (scope label, totals, per-session file groups, item-level status chips).
- [x] Filter empty runtime todo artifact files from API/UI so operators see actionable task state, not `[]` placeholders.
- [x] Add behavioral tests for runtime todos service + API endpoint (real files on disk, auth enforcement, normalized payload assertions).
- [x] Add explicit permission-decision feed card (`tool_permission_decision`) driven by trace/session events so operators can audit allow/deny outcomes separate from tool results.
- [ ] Add Claude runtime artifact browser card (history/debug/notes) with safe redaction and per-scope filtering.

## P1: DRY Architecture Refactor

- [x] Extract chat orchestration from `+page.svelte` into `chat-orchestrator` store/service.
- [x] Keep presentational components pure (`ChatPanel`, `SessionSidebar`, `TaskSidebar`, `Composer`).
- [x] Compose chat surface from focused components (`ChatHeaderBar`, `ChatMessageList`, `ChatComposer`, `TaskDetailPanel`, `SessionListItem`).
- [x] Extract reusable UI primitives for overlay/chips (`SuggestionOverlay`, `AgentIdentityChip`) to avoid duplicated markup.
- [ ] Generate or centralize protocol types once; avoid drift between backend payloads and TS unions.
- [x] Centralize model and agent option mapping functions (no duplicated parsing logic).
- [x] Move all endpoint calls into `frontend/src/lib/api/` client layer.

## P1: Modern Interaction Quality

- [x] Add split-view resize memory (persist width per mode).
- [x] Add smooth list virtualization for large session/message histories.
- [x] Add optimistic UI with rollback for rename/delete actions.
- [x] Improve toast system with stack/queue and dedupe.
- [x] Add visible connection health state + manual reconnect action.

## P2: Visual and Product Polish

- [ ] Redesign composer to feel premium and intentional while keeping system personality.
- [ ] Add subtle status transitions for routing/thinking/streaming/done.
- [x] Add in-chat runtime status strip with themed phase chips and click-to-expand execution details.
- [x] Render expandable assistant runtime timeline blocks in transcript (thinking/reasoning/tool calls/results/todos) with muted collapsed preview copy.
- [ ] Add compact/comfortable density toggle.
- [x] Add professional LLM runtime strip in chat header (active model, backend, availability, tool/stream support, context pressure including `Context Full`).
- [x] Add per-agent identity chips in header and transcript.
- [x] Add staged capability rail in composer for voice, image, audio, and file inputs with attachment chips for future backend wiring.
- [ ] Replace staged attachment/voice placeholders with real backend protocol support (upload metadata, ingestion status, failure recovery).
- [ ] Improve mobile behavior below 1024px.
- [x] Expand theme system beyond colors: component behavior tokens now drive status bar, mode rail indicators, resize handles, tool expansion, and confirm countdown style.
- [x] Add RTS-style mission-control theme (`tactical-rts`) with dedicated typography, atmosphere, and interaction profile.
- [x] Upgrade portrait lifecycle states and SVG motion behavior (thinking/streaming/done/error assets + smooth/stepped animation styles).
- [ ] Add production portrait asset pack + responsive sizing tokens across sidebar/header/task cards + visual regression coverage.

## P1: Prototype-Derived UI Components (Stitch + Codex Patterns)

- [x] Build `SecurityDomainSidebar` (domain filters, policy counts, agent scope chips).
- [x] Build `PermissionPolicyCard` (tool id, policy state, risk badge, trust meter, confirm requirement).
- [x] Build `SecurityEventFeed` (live/queued/allowed/denied rows with timestamps and quick drill-down).
- [x] Build `AgentIdentityBlueprintCard` (portrait slot, name, role, color, tone/persona controls).
- [x] Build `AgentSkillMatrixCard` (grouped capabilities + enable/disable states + missing dependency indicators).
- [x] Build `AgentModelRoutingCard` (reasoning/code/rapid lanes with ordered fallback models + health).
- [x] Build `ServiceConnectionsCard` (integration status, auth freshness, reconnect/manage actions).
- [x] Build `ValidationRail` (run counts, avg cost, error rate, uptime, dependency checks, quota accordions, audit logs).
- [x] Build `DispatchCommandBar` (pause/resume dispatches, create dispatch, filters).
- [x] Build `TaskRunCard` variants: `log-stream`, `progress`, and `diff-preview`.
- [x] Build `TaskMetricsRibbon` (active agents, session spend, token/context pressure, connection health).
- [x] Build `TaskFilterBar` (search + state chips + agent chips + model chips).
- [x] Build `ExecutionTimelineView` (prompt/tool/output/diff as chronological blocks per turn).
- [x] Build `InlineDiffReviewCard` (file path, hunks, approve/reject/comment hooks).
- [ ] Wire `InlineDiffReviewCard` to live backend diff payloads and persist approve/reject/comment actions.
- [x] Add shared card primitives (`MetricCard`, `StatusChip`, `SectionAccordion`, `TraceBadge`) to keep UI DRY.
- [x] Add Storybook runtime-state coverage for backend-driven agent profile cards (identity, prompt identity, tools/permissions, connections, prompt inspector, permission matrix).

## Runtime Warnings and Layout Integrity

- [x] Remove noisy e2e startup warning path by supporting backend-disabled frontend startup mode for static previews/tests.
- [x] Reduce startup/build warnings via Vite manual chunking for markdown/highlighting dependencies.
- [x] Enforce full-viewport rendering baseline (`html/body` reset + `min-h-dvh` shell) so component panes reliably fill available space.

## Testing and Quality Gates

- [ ] Unit: protocol parsing and message reducers.
- [x] Unit: mention parser and slash command parser.
- [x] Unit: model selection state transitions.
- [x] Unit: session history reducers and hydration behavior.
- [x] Integration: websocket flow with real backend process.
- [ ] Integration: sqlite session/message persistence and retrieval.
- [x] Integration: tool permission decision event flow (runtime callback -> session/run persistence -> frontend replay rendering).
- [x] E2E: new chat, multiple chats, resume history, explicit `@agent` routing.
- [x] E2E: manual model override and preferred model reset.
- [x] E2E: task dispatch visibility and completion.
- [ ] Accessibility: focus trap, keyboard nav, aria-live coverage.
- [ ] Performance: large transcript render budget and session list responsiveness.
- [x] Manual live smoke: Playwright browser chat against running backend + Ollama with persisted session/message verification.
- [x] E2E: backend-enabled Playwright spec for live chat send + streaming settle + session-history API verification.
- [x] E2E: backend-enabled Playwright spec validates explicit Ollama model selection and run metadata for a live turn.
- [x] E2E: direct-agent memory-context recall flow (seed memory → prompt preview contains token → chat response returns token).
- [x] E2E: create new agent from Agents UI and validate policy matrix allow/confirm/deny wiring.
- [ ] E2E: strict memory+Cognee backend contract assertions in Ollama flow when `/api/memory/backends` is enabled in live backend runtime.
- [ ] E2E: policy enforcement flow proving tool calls are allowed/denied/confirm-gated according to agent policy (real backend + real model).
- [x] E2E: mobile viewport interaction quality for composer overlays (`@`, `/`, model picker), send/interrupt controls, and session/task panes.

## Storybook Coverage

- [x] Storybook static build succeeds on current branch (`pnpm build-storybook`).
- [x] Add missing component stories so all core chat surfaces render in Storybook:
- [x] `AgentIdentityChip`, `AgentPortrait`, `ChatComposer`, `ChatHeaderBar`, `ChatMessageList`
- [x] `MessageRuntimeTimeline`
- [x] `PermissionDecisionFeedCard`
- [x] `ConfirmCard`, `ConnectionToast`, `ErrorBanner`, `MessageContent`, `ModeRail`
- [x] `RecipientPicker`, `ResizeHandle`, `SessionListItem`, `StatusBar`, `SuggestionOverlay`
- [x] `TaskDetailPanel`, `TaskSidebar`, `ThemeSelector`, `ToastStack`, `TraceTimelinePanel`

## Test Logging and CI Hygiene

- [x] Add frontend test task wrappers that tee output into `tests/output/`.
- [x] Add backend test wrappers that tee output into `tests/output/`.
- [x] Include timestamped log filenames in all scripted test runs.
- [x] Store live websocket and Playwright smoke logs/screenshots under `tests/output/`.
- [ ] Add CI artifact upload for test logs and Playwright traces.

## Suggested Implementation Order

- [x] Step 1: Huginn YAML + init payload correctness.
- [x] Step 2: Session transcript persistence + APIs + sidebar wiring.
- [x] Step 3: `@agent` end-to-end path (composer to backend routing).
- [x] Step 4: Model override correctness with Claude SDK constraints.
- [x] Step 5: Model selector UX rewrite.
- [x] Step 6: Slash commands and skills passthrough.
- [ ] Step 7: Task dispatch completion and task replay.
- [ ] Step 8: DRY refactor and large-scale test hardening.
