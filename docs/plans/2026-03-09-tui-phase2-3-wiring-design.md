# TUI Phase 2/3 Wiring — Design Document

**Date:** 2026-03-09
**Scope:** Fix bugs, wire stubbed commands, complete Phase 2/3 functionality
**Excludes:** Phase 4 (setup/settings screens), Phase 5 (split mode, themes, WebSocket gateway)

---

## Context

Audit of the TUI revealed the backend is fully implemented (SessionManager, MemoryHub, dispatch pipeline, event system) but 17 TUI commands are stubbed and several bugs exist. The TUI runs the full Corvus gateway in-process — all data is real, just not surfaced.

## Architectural Issues Discovered During Audit

### Token count always 0 (FIXED)
`run_executor.py` and `background_dispatch.py` used `getattr(sdk_message, "total_input_tokens", 0)` but the SDK's `ResultMessage` stores tokens in `usage: dict` with `input_tokens`/`output_tokens` keys. Fixed to read from `sdk_message.usage`.

### Agent conversation context is stateless (CRITICAL — must fix)
Each `execute_agent_run()` creates a new `ClaudeSDKClient` via `async with`, which spawns a new Claude Code CLI subprocess, runs one query, then kills the process. The agent has **zero memory of prior messages**.

**However, the SDK is designed for persistent connections.** `ClaudeSDKClient` supports `connect()` once → `query()` multiple times. The CLI subprocess maintains full conversation context across queries. We're throwing this away.

**Fix:** Keep SDK clients alive per (session, agent) pair. Add an `AgentClientPool` to `ChatSession` that caches live `ClaudeSDKClient` instances. When a second message arrives for the same agent, reuse the existing client instead of creating a new one. Tear down all clients when the session ends.

This also means:
- Streaming works naturally (agent sees prior context, responds faster)
- Multi-turn reasoning works ("now fix the bug I described")
- Token costs drop (no re-encoding prior context from scratch — CLI handles it)
- The workspace persistence we fixed becomes even more important (client's CWD stays valid)

**Implementation approach:**
```
ChatSession
  └── _agent_clients: dict[str, ClaudeSDKClient]  # keyed by agent_name

execute_agent_run():
  client = session.get_or_create_client(agent_name, options)
  await client.query(message)  # Reuses existing connection

ChatSession.teardown():
  for client in _agent_clients.values():
      await client.__aexit__()  # Kills subprocess
```

### Workspace lifecycle corrected
Original cleanup deleted workspaces after every single run — destroying agent state between messages. Corrected to:
- **Create** workspace on first message to an agent in a session
- **Reuse** workspace for subsequent messages (same session+agent)
- **Clean up** when session ends (TUI disconnect, WebSocket disconnect, background dispatch completion)
- **Prune stale** on server/TUI startup (for crash recovery)

## Work Groups

### Group A: Bug Fixes + Quick Wins

#### A1. Fix `render_memory_results()` title parameter
- **Bug:** `app.py` passes `title=` kwarg but `renderer.render_memory_results()` doesn't accept it
- **Fix:** Add `title: str = "Memory Results"` parameter to the method signature, use it in the panel header

#### A2. Wire tool tab-completion
- **Bug:** `completer.update_tools()` exists but is never called
- **Fix:** After `gateway.list_agent_tools()` in `app.run()`, call `self.completer.update_tools(tool_names)`. Also update tools when agent switches (`/agent`, `/enter`, `/back`, `/top`).

#### A3. Validate agent names against registry
- **Bug:** Agent stack accepts any string
- **Fix:** In `_handle_system_command` for `/agent <name>`, check `gateway.list_agents()` first. Render error if not found. Same for `/enter`.

#### A4. Render message history on session resume
- **Bug:** `session resume` loads messages from DB but doesn't display them
- **Fix:** After `session_manager.resume()` returns `SessionDetail`, iterate `detail.messages` and render each via `render_user_message()` / `render_agent_message()` as appropriate. Add a visual separator (e.g., "── Resumed session {id} ──") before the history.

#### A5. Persistent SDK clients per (session, agent) — multi-turn context
- **Bug:** Each message creates a new `ClaudeSDKClient`, destroying all conversation context
- **Fix:** Add `AgentClientPool` to `ChatSession` that caches live `ClaudeSDKClient` instances keyed by agent name. In `execute_agent_run`, check if a client already exists for this agent — if so, reuse it with `client.query()`. If not, create one, `connect()` it, store it, then `query()`.
- **Impact:** Agents maintain full conversation context across turns. Streaming is faster (no subprocess startup). Token costs decrease.
- **Complication:** `build_backend_options()` constructs options per-run (including dynamic model selection). Need to either fix options at client creation time or rebuild client when model changes.

**Client lifecycle — idle timeout (Option 3):**

| Scenario | Behavior |
|----------|----------|
| Interactive chat | Client alive while chatting, idle timeout after 10 min of no messages |
| Spawned background agent | Client alive while task runs, idle timeout after completion |
| Cron/background dispatch | Client alive for task duration, immediate cleanup when dispatch ends (one-shot) |
| Model change (`/model`) | Tear down existing client for that agent, next message creates fresh client with new model |

**Implementation:**
```python
@dataclass
class PooledClient:
    client: ClaudeSDKClient
    agent_name: str
    last_activity: float        # time.monotonic()
    active_run: bool = False    # True while query() is in flight

class AgentClientPool:
    _clients: dict[str, PooledClient]
    _idle_timeout: float = 600  # 10 minutes

    async def get_or_create(self, agent_name, options) -> ClaudeSDKClient:
        if agent_name in self._clients:
            entry = self._clients[agent_name]
            entry.last_activity = time.monotonic()
            return entry.client
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._clients[agent_name] = PooledClient(client=client, agent_name=agent_name, ...)
        return client

    async def release(self, agent_name):
        """Mark run complete, start idle timer."""
        if agent_name in self._clients:
            self._clients[agent_name].active_run = False
            self._clients[agent_name].last_activity = time.monotonic()

    async def evict_idle(self):
        """Called periodically — tear down clients idle > timeout."""
        now = time.monotonic()
        for name, entry in list(self._clients.items()):
            if not entry.active_run and (now - entry.last_activity) > self._idle_timeout:
                await entry.client.__aexit__(None, None, None)
                del self._clients[name]

    async def teardown_all(self):
        """Session end — kill all clients."""
        for entry in self._clients.values():
            await entry.client.__aexit__(None, None, None)
        self._clients.clear()
```

Pool lives on `ChatSession`. Idle eviction runs on a timer (asyncio task, every 60s). Background dispatches call `teardown_all()` immediately after completion since they're one-shot.

#### A6. Fix status bar model name
- **Bug:** Model name in status bar is static
- **Fix:** Track current model in app state. Update when `/model` command is wired (A7). For now, pull default model from runtime.

---

### Group B: Wire Commands with Ready Backends

#### B1. `/status` — Session & system status
- **Backend:** `session_mgr.get()` for current session, `list_agent_runs(status=...)` for active runs
- **Implementation:** Render a Rich table showing:
  - Current session ID, agent, started_at, message count
  - Active agent runs system-wide (agent, status, model, duration)
  - Token totals, cost totals for current session

#### B2. `/export [path]` — Export session to markdown
- **Backend:** `session_mgr.session_to_markdown()` already exists as a static method
- **Implementation:** Call with current session's messages/events, write to file (default: `session-{id}.md`). Render confirmation with path.

#### B3. `/models` — List available models
- **Backend:** `gateway.list_models()` already implemented
- **Implementation:** Render Rich table with model ID, backend, context limit, supports_tools flag. Mark current model.

#### B4. `/model <name>` — Switch model
- **Backend:** Need to add model selection to InProcessGateway or pass through to ChatSession
- **Implementation:** Validate model exists via `list_models()`. Store in app state. Pass as `user_model` on next `send_message()`. Update status bar.

#### B5. `/tool-history` — Recent tool calls
- **Backend:** `session_mgr.list_run_events(run_id)` and `list_dispatch_events(dispatch_id, event_type="tool_result")` exist
- **Implementation:** Query recent tool events for current session. Render table: timestamp, agent, tool_name, status, duration. Limit to last 20.

#### B6. `/audit [limit]` — Audit trail
- **Backend:** `session_mgr.list_trace_events()` with rich filtering exists
- **Implementation:** Query recent trace events. Render table: timestamp, source, event_type, agent, summary. Support optional `--agent` or `--type` filters via args parsing.

---

### Group C: Session History, Spawn, Workers, System-Wide Status

#### C1. Session resume with history replay
- Builds on A4. When resuming:
  1. Render separator: `"── Resumed: {summary} ({time_ago}) ──"`
  2. Replay messages in order (user → agent, with tool calls inline if available)
  3. Restore agent stack to the agent that was active when session ended
  4. Continue accepting input in that session context

#### C2. `/spawn <agent> [task]` — Two modes

**Mode A (no task):** Push agent onto stack as child, route next message to it.
```
/spawn codex
→ Spawned @codex as child of @work
→ (next message goes to codex)
```
- Call `agent_stack.spawn(agent_name)` (already exists)
- Validate agent name against registry first
- Update tool completion for new agent

**Mode B (with task):** Dispatch a background task to the agent immediately.
```
/spawn codex review the auth module for security issues
→ Dispatched background task to @codex: "review the auth module..."
→ (you continue chatting with current agent)
```
- Call `gateway.send_message(task, requested_agent=agent_name)` but don't switch context
- The dispatch runs in background, events still flow to event handler
- Status bar shows the active run

#### C3. `/summon <agent>` — Pull agent into current context
- Alias for `/spawn <agent>` (Mode A). Creates child relationship and switches focus.
- If agent is already a child, just switch to it (like `/enter`).

#### C4. `/workers` — Active workers panel
- **Data sources:**
  - Local: `agent_stack.current.children` (agents spawned in this session)
  - System-wide: `session_mgr.list_agent_runs(status="running")` (all active runs)
- **Render:** Two-section table:
  - **My Workers:** Children of current agent with status badges (THINKING/EXECUTING/IDLE)
  - **System Activity:** All active runs across all sessions (agent, session_id, model, duration, tokens)
- **Navigable:** `/workers` shows the list; user can `/enter <agent>` to switch to a local worker, or a future `/watch <run_id>` could tail a system run's output

#### C5. System-wide status bar
- **Current:** `@codex │ opus │ ⚡1 worker │ 45.1k tok │ $0.22`
- **New:** `@codex │ opus │ ⚡1 mine · 3 system │ 45.1k tok │ $0.22`
- **Implementation:**
  - Add a periodic poll (every 2-3 seconds) or query on each prompt redraw
  - Call `session_mgr.list_agent_runs()` filtered to active statuses
  - Partition into "mine" (current session_id) vs "system" (everything else)
  - Update status bar formatter

**Polling approach:** The status bar's `__call__` is invoked on every prompt redraw by prompt_toolkit. We can cache the system-wide count with a short TTL (2-3 seconds) to avoid hammering SQLite on every keystroke.

```python
# status_bar.py
def _active_run_counts(self) -> tuple[int, int]:
    """Return (my_active, system_active) with 3s cache."""
    now = time.monotonic()
    if now - self._last_poll < 3.0:
        return self._cached_counts
    runs = self._session_mgr.list_agent_runs()  # all runs
    active = [r for r in runs if r["status"] in ("running", "queued", "thinking", "executing")]
    mine = sum(1 for r in active if r.get("session_id") == self._session_id)
    system = len(active) - mine
    self._cached_counts = (mine, system)
    self._last_poll = now
    return (mine, system)
```

#### C6. Cost tracking in status bar
- `RunComplete` events already carry `cost_usd`
- Add `cost_usd` accumulation to `TokenCounter` (alongside token tracking)
- Display in status bar: `$0.22` format

---

## Protocol Layer Changes

### InProcessGateway additions needed:
1. `list_active_runs() -> list[dict]` — wraps `session_mgr.list_agent_runs()` with active status filter
2. `get_session_detail(session_id) -> SessionDetail` — already exists as `resume_session()`
3. `set_model(model_name)` — stores preference, validates against `list_models()`

### GatewayProtocol additions:
- Add `list_active_runs()` to the abstract interface
- Add `set_model()` to the abstract interface

---

## Renderer additions needed:

| Method | For | Returns |
|--------|-----|---------|
| `render_session_history(messages, separator_text)` | C1 | Renders replayed messages with separator |
| `render_status_table(session_info, active_runs)` | B1 | Rich table with session + system status |
| `render_export_confirmation(path)` | B2 | System message with file path |
| `render_models_list(models, current)` | B3 | Table with model list |
| `render_tool_history(events)` | B5 | Table with recent tool calls |
| `render_audit_log(events)` | B6 | Table with trace events |
| `render_workers(local, system)` | C4 | Two-section workers panel |

---

## Execution Order

1. **A1–A5** (bug fixes) — independent, can parallelize
2. **B1–B6** (wire commands) — mostly independent, B4 depends on B3
3. **C5** (status bar) — foundation for C2/C4 visibility
4. **C1** (session resume replay) — standalone
5. **C2/C3** (spawn/summon) — needs C5 to see background runs
6. **C4** (workers panel) — needs C5 data + C2 to have workers to show
7. **C6** (cost tracking) — standalone, can go anywhere

---

## Testing

All tests behavioral (no mocks per project policy):
- **Bug fixes:** Test against real renderer output, real completer state
- **Commands:** Test full chain: command input → gateway call → DB query → rendered output
- **Status bar:** Test with real SessionManager, seed DB with test runs, verify formatted output
- **Spawn:** Test agent stack state + verify gateway receives correct message routing
- **Session replay:** Seed DB with messages, resume, verify all messages rendered in order
