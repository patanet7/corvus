---
subsystem: gateway/session-management
last_verified: 2026-03-09
---

# Session Management and Chat Protocol

`ChatSession` (`corvus/gateway/chat_session.py`) is the thin coordinator class for WebSocket chat lifecycle. It owns session state, delegates dispatch to `DispatchOrchestrator`, and agent execution to `RunExecutor`. The WebSocket protocol contract is defined in `corvus/gateway/protocol.py`.

## Ground Truths

- `ChatSession` holds: `GatewayRuntime`, `WebSocket` (nullable for non-WS callers), `user`, `session_id`, `SessionTranscript`, `ConfirmQueue`, `SessionEmitter`, and a nullable `_current_turn: TurnContext`.
- `TurnContext` is a per-turn `@dataclass(slots=True)` with: `dispatch_id`, `turn_id`, `dispatch_interrupted` (asyncio.Event), `user_model`, `requires_tools`.
- `ChatSession.run()` sends an `init` message (models, agents, default agent, session ID), then enters the main message loop handling: `ping`/`pong`, `interrupt`, `confirm_response`, and `chat` messages.
- Degraded mode activates when no LLM backend is configured; only ping/pong and error responses are served.
- `SessionEmitter` handles three responsibilities: WebSocket delivery (under asyncio.Lock), session/run event persistence to SQLite, and trace publication to `TraceHub`.
- Event types are classified into three `frozenset`s in `protocol.py`: `PERSISTED_SESSION_EVENT_TYPES` (16 types), `PERSISTED_RUN_EVENT_TYPES` (9 types), `TRACE_EVENT_TYPES` (superset including routing/status/error).
- The dispatch lifecycle follows: `dispatch_start` -> `dispatch_plan` -> per-agent `run_start` -> `run_phase` (queued/routing/planning/executing/compacting) -> `run_output_chunk` (ordered by `chunk_index`, terminal chunk has `final=true`) -> `run_complete` -> `dispatch_complete` -> `done`.
- Backward-compatible task events (`task_start`, `task_progress`, `task_complete`) are still emitted alongside the run lifecycle.
- During active dispatch, a concurrent `dispatch_control_listener` handles interrupt, ping, confirm_response, and rejects new prompts with `dispatch_in_progress` error.
- Persistence uses three tables: `dispatches`, `agent_runs`, `run_events` (managed by `SessionManager`).
- `DispatchControlRegistry` tracks active dispatches with interrupt events; interrupts set `dispatch_interrupted` and propagate via `asyncio.CancelledError`.
- The current SDK pattern creates a throwaway `ClaudeSDKClient` per run (`async with ClaudeSDKClient`), losing conversation context between messages. The planned `SDKClientManager` will provide persistent multi-turn clients with session resume via `resume=sdk_session_id`.
- `set_ws_interceptor()` allows non-WebSocket callers (TUI in-process protocol) to receive outbound payloads without a real WebSocket.
- Run results include: `cost_usd`, `tokens_used`, `context_limit`, `context_pct`.

## Boundaries

- **Depends on:** `SessionEmitter`, `DispatchOrchestrator`, `RunExecutor`, `ChatEngine`, `ConfirmQueue`, `SessionManager`, `DispatchControlRegistry`
- **Consumed by:** `corvus/api/chat.py` (WebSocket endpoint), `corvus/tui/protocol/in_process.py` (TUI), `corvus/gateway/background_dispatch.py` (webhooks/scheduler)
- **Does NOT:** classify intents (defers to ChatEngine/RouterAgent), enforce tool permissions (defers to security stack), manage SDK client pools (currently throwaway, planned SDKClientManager)
