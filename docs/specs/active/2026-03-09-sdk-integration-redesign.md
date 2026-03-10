---
title: "SDK Integration Redesign: Full Agent SDK Utilization"
type: spec
status: approved
date: 2026-03-09
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# SDK Integration Redesign — Full Agent SDK Utilization

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-03-09
**Scope:** Replace throwaway ClaudeSDKClient pattern with persistent, fully-featured SDK integration
**Depends on:** Workspace lifecycle fixes (already landed), token bug fix (already landed)
**Supersedes:** Section A5 of `2026-03-09-tui-phase2-3-wiring-design.md`

---

## Problem Statement

Corvus creates and destroys a `ClaudeSDKClient` subprocess on **every single message** (`run_executor.py:295`, `background_dispatch.py:350`). This is architecturally wrong — the SDK is designed for `connect()` once, `query()` many times with persistent conversation context.

**Consequences of the current pattern:**
- Zero conversation context between messages (agent can't reference prior turns)
- Full subprocess startup cost every turn (~2-3s)
- No ability to interrupt (client gone between turns)
- No streaming (complete messages only, no token-level deltas)
- No model switching on a live client
- No file checkpointing or rewind
- No session resume across process restarts
- No inter-agent communication

**15 SDK features we don't use at all:**

| Feature | SDK Method | Current Status |
|---------|-----------|----------------|
| Persistent multi-turn | `connect()` + repeated `query()` | Create/destroy per message |
| Token streaming | `include_partial_messages=True` + `StreamEvent` | Not set |
| Interrupt | `client.interrupt()` | Hacked via `asyncio.CancelledError` |
| Model switch | `client.set_model()` on live client | Rebuild client entirely |
| Permission mode switch | `client.set_permission_mode()` | Static at creation |
| Session resume | `resume=session_id` in options | Not used |
| Session fork | `fork_session=True` | Not used |
| File checkpointing | `enable_file_checkpointing=True` | Not used |
| File rewind | `client.rewind_files(user_message_id)` | Not used |
| MCP status | `client.get_mcp_status()` | Not used |
| Dynamic MCP | `client.add_mcp_server()` / `remove_mcp_server()` | Not used |
| Server info | `client.get_server_info()` | Not used |
| Budget/turn limits | `max_turns`, `max_budget_usd` | Not used |
| Fallback model | `fallback_model` option | Not used |
| Extended thinking | `thinking` / `effort` options | Not used |
| Agent Teams | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | Not used |

---

## SDK API Reference

### ClaudeSDKClient Full API

Source: [platform.claude.com/docs/en/agent-sdk/python](https://platform.claude.com/docs/en/agent-sdk/python)

```python
class ClaudeSDKClient:
    def __init__(self, options: ClaudeAgentOptions | None = None, transport: Transport | None = None)
    async def connect(self, prompt: str | AsyncIterable[dict] | None = None) -> None
    async def query(self, prompt: str | AsyncIterable[dict], session_id: str = "default") -> None
    async def receive_messages(self) -> AsyncIterator[Message]
    async def receive_response(self) -> AsyncIterator[Message]
    async def interrupt(self) -> None
    async def set_permission_mode(self, mode: str) -> None
    async def set_model(self, model: str | None = None) -> None
    async def rewind_files(self, user_message_id: str) -> None
    async def get_mcp_status(self) -> dict[str, Any]
    async def add_mcp_server(self, name: str, config: McpServerConfig) -> None
    async def remove_mcp_server(self, name: str) -> None
    async def get_server_info(self) -> dict[str, Any] | None
    async def disconnect(self) -> None
```

### Persistent Multi-Turn Pattern

Source: [platform.claude.com/docs/en/agent-sdk/python](https://platform.claude.com/docs/en/agent-sdk/python) — "Build Continuous Conversation Interface"

```python
# The SDK is designed for this — connect once, query many times:
client = ClaudeSDKClient(options)
await client.connect()

await client.query("Analyze the auth module")
async for msg in client.receive_response(): ...

# Second query: automatically continues the same conversation
await client.query("Now refactor it to use JWT")
async for msg in client.receive_response(): ...

# Context is maintained across all queries
await client.disconnect()
```

### Session Resume and Fork

Source: [platform.claude.com/docs/en/agent-sdk/sessions](https://platform.claude.com/docs/en/agent-sdk/sessions)

Sessions persist to `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl`. Resume via `resume=session_id`. Fork via `fork_session=True` (branches without altering original).

```python
# Resume: pick up exactly where we left off
async for message in query(
    prompt="Continue from where we left off",
    options=ClaudeAgentOptions(resume=session_id),
): ...

# Fork: branch into alternative without losing original
async for message in query(
    prompt="Try a different approach instead",
    options=ClaudeAgentOptions(resume=session_id, fork_session=True),
): ...
```

### StreamEvent (Token-Level Streaming)

Source: [platform.claude.com/docs/en/agent-sdk/streaming-output](https://platform.claude.com/docs/en/agent-sdk/streaming-output)

With `include_partial_messages=True`, the stream yields `StreamEvent` objects **before** complete `AssistantMessage` objects:

```python
@dataclass
class StreamEvent:
    uuid: str
    session_id: str
    event: dict[str, Any]       # Raw Claude API stream event
    parent_tool_use_id: str | None  # Set when event is from a subagent
```

Event flow:
```
StreamEvent (message_start)
StreamEvent (content_block_start)  — type: "text" | "tool_use" | "thinking"
StreamEvent (content_block_delta)  — text_delta | input_json_delta | thinking_delta
StreamEvent (content_block_stop)
StreamEvent (message_delta)
StreamEvent (message_stop)
AssistantMessage                   — complete message with all content blocks
ResultMessage                      — final result with usage/cost
```

**Limitation:** Extended thinking (`thinking` config) disables `StreamEvent` messages. Cannot use both simultaneously.

### File Checkpointing

Source: [platform.claude.com/docs/en/agent-sdk/file-checkpointing](https://platform.claude.com/docs/en/agent-sdk/file-checkpointing)

Enable with `enable_file_checkpointing=True`. Capture `UserMessage.uuid` values as checkpoint IDs. Only tracks changes through Write, Edit, NotebookEdit tools — not Bash file mutations.

### Subagents

Source: [platform.claude.com/docs/en/agent-sdk/subagents](https://platform.claude.com/docs/en/agent-sdk/subagents)

Pass `AgentDefinition` objects via `agents` dict. Parent uses `Agent` tool (formerly `Task`, renamed v2.1.63) to spawn subagents. Subagents run in isolated contexts, return results to parent. Currently no recursive subagents (no `Agent` in subagent tools).

### Agent Teams

Source: [code.claude.com/docs/en/agent-teams](https://code.claude.com/docs/en/agent-teams)

CLI-level feature (not a Python SDK API). Enabled via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Since our SDK clients **are** Claude Code CLI subprocesses, we can activate this by injecting env vars.

**7 core primitives:** `Teammate` (spawn/lifecycle), `SendMessage` (direct/broadcast), `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, `TeamDelete`.

**Communication:** File-based inbox/mailbox at `~/.claude/teams/{team}/inboxes/{agent}.json`. Messages are JSON objects with `from`, `text`, `summary`, `timestamp`, `read` fields.

**Message types:** `message`, `broadcast`, `shutdown_request`, `shutdown_response`, `plan_approval_response`, `idle_notification`.

**Task dependencies:** `TaskCreate` supports `addBlockedBy` — blocked tasks auto-unblock when dependencies complete.

**Hooks:** `TeammateIdle` (runs when teammate finishes — exit code 2 sends feedback and keeps it working), `TaskCompleted` (runs when task marked complete — exit code 2 prevents completion).

**Env vars injected per teammate:**
```
CLAUDE_CODE_TEAM_NAME
CLAUDE_CODE_AGENT_ID
CLAUDE_CODE_AGENT_NAME
CLAUDE_CODE_AGENT_TYPE
CLAUDE_CODE_PLAN_MODE_REQUIRED
```

**Known limitations:** No session resume with teammates, no nested teams, one team per session, lead is fixed, permissions set at spawn, no force-kill on unresponsive teammates.

---

## Architecture Decision: Hybrid Routing

**Corvus routes at the top level, SDK handles conversation continuity and subagent self-delegation.**

- `AgentsHub` / `TaskPlanner` / `ChatEngine` continue to decide which agent handles a message
- Each agent gets a persistent `ClaudeSDKClient` via `SDKClientManager`
- Sibling agents are passed via the `agents` dict on `ClaudeAgentOptions` so agents can self-delegate when appropriate
- Agent Teams env vars are injected so agents can communicate directly when team mode is active
- Corvus's security stack (`PolicyEngine`, `can_use_tool`, hooks, `ConfirmQueue`, audit, sanitizer) remains fully intact — security is orthogonal to connection lifetime

## Architecture Decision: Dual Session Persistence

**Both Corvus and SDK persist sessions. SDK handles conversation continuity, Corvus handles metadata/audit/UI.**

- SDK sessions persist automatically to `~/.claude/projects/<cwd>/<session_id>.jsonl`
- Corvus's `SessionManager` continues to track sessions, messages, runs, events, dispatches in SQLite
- On resume: try SDK's native `resume=session_id` first (full context restoration), fall back to Corvus context replay if SDK session file is missing
- `ManagedClient` captures `sdk_session_id` from `ResultMessage.session_id` for later resume

## Architecture Decision: Full StreamEvent Support

**Token-level streaming from day one.** `include_partial_messages=True` on all clients.

- Text streams character-by-character to TUI/WebSocket
- Tool calls show "Using Bash..." as they start, not after completion
- Thinking blocks visible in real-time (when not using StreamEvent — limitation noted)
- Subagent events tagged with `parent_tool_use_id` for UI differentiation

---

## New Components

### 1. `SDKClientManager` — `corvus/gateway/sdk_client_manager.py`

The **sole interface** between Corvus and `ClaudeSDKClient`. No other code imports or instantiates SDK clients directly.

```
GatewayRuntime
  └── sdk_client_manager: SDKClientManager
        ├── _pools: dict[str, AgentClientPool]    # keyed by session_id
        │     └── _clients: dict[str, ManagedClient]  # keyed by agent_name
        ├── _teams: dict[str, TeamContext]          # keyed by team_name
        ├── _idle_timeout: float = 600              # 10 minutes
        └── _eviction_task: asyncio.Task            # periodic cleanup
```

**Full public API:**

```python
class SDKClientManager:
    def __init__(self, runtime: GatewayRuntime):
        ...

    # --- Client lifecycle ---
    async def get_or_create(
        self, session_id: str, agent_name: str,
        options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient
    async def get_or_resume(
        self, session_id: str, agent_name: str,
        options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient
        # Try SDK resume first (checks SessionManager for stored sdk_session_id),
        # fall back to fresh client
    async def release(self, session_id: str, agent_name: str) -> None
        # Mark idle, start timeout countdown
    async def teardown_session(self, session_id: str) -> None
        # Kill all clients for a session
    async def teardown_all(self) -> None
        # Server shutdown — kill everything

    # --- Conversation ---
    async def query(self, session_id: str, agent_name: str, prompt: str) -> None
    def receive_response(self, session_id: str, agent_name: str) -> AsyncIterator[Message]
    def receive_stream(self, session_id: str, agent_name: str) -> AsyncIterator[StreamEvent | Message]

    # --- Control ---
    async def interrupt(self, session_id: str, agent_name: str) -> None
    async def set_model(self, session_id: str, agent_name: str, model: str) -> None
        # Tears down existing client, next get_or_create builds fresh with new model
    async def set_permission_mode(self, session_id: str, agent_name: str, mode: str) -> None

    # --- Session persistence ---
    async def resume_sdk_session(
        self, session_id: str, agent_name: str,
        sdk_session_id: str, options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient
    async def fork_session(self, session_id: str, agent_name: str) -> str
        # Returns new sdk_session_id

    # --- File checkpointing ---
    async def rewind_files(self, session_id: str, agent_name: str, checkpoint_id: str) -> None

    # --- MCP management ---
    async def get_mcp_status(self, session_id: str, agent_name: str) -> dict
    async def add_mcp_server(self, session_id: str, agent_name: str, name: str, config: dict) -> None
    async def remove_mcp_server(self, session_id: str, agent_name: str, name: str) -> None

    # --- Info/diagnostics ---
    async def get_server_info(self, session_id: str, agent_name: str) -> dict | None
    async def list_active_clients(self) -> list[ClientInfo]

    # --- Team coordination (plumbed, not surfaced) ---
    async def create_team(self, session_id: str, team_name: str) -> TeamContext
    async def add_to_team(self, session_id: str, agent_name: str, team_name: str) -> None
    async def remove_from_team(self, session_id: str, agent_name: str) -> None
    async def teardown_team(self, team_name: str) -> None
    async def read_inbox(self, agent_name: str, team_name: str) -> list[TeamMessage]
    async def send_team_message(self, from_agent: str, to_agent: str, text: str, team_name: str) -> None
    async def broadcast(self, from_agent: str, text: str, team_name: str) -> None
    async def create_team_task(self, team_name: str, subject: str, description: str, owner: str | None = None) -> str
    async def update_team_task(self, team_name: str, task_id: str, status: str, owner: str | None = None) -> None
    async def list_team_tasks(self, team_name: str) -> list[TeamTask]

    # --- Maintenance ---
    async def evict_idle(self, timeout: float | None = None) -> int
        # Returns count evicted
    async def start_eviction_loop(self, interval: float = 60.0) -> None
    async def stop_eviction_loop(self) -> None
```

**Client creation flow:**
1. Caller: `sdk_manager.get_or_create(session_id, agent_name, options_builder)`
2. Check pool for existing live client for `(session_id, agent_name)` → return if found, update `last_activity`
3. If not found, call `options_builder()` to get fresh `ClaudeAgentOptions`
4. Inject `include_partial_messages=True` and `enable_file_checkpointing=True`
5. If team is active for this session, inject team env vars
6. Create `ClaudeSDKClient(options=opts)`, call `await client.connect()`
7. Wrap in `ManagedClient`, store in pool
8. Return `ManagedClient`

**`get_or_resume` flow (for session continuity across restarts):**
1. Check pool for existing live client → return if found
2. Query Corvus `SessionManager` for stored `sdk_session_id` for this `(session_id, agent_name)`
3. If found, build options with `resume=sdk_session_id`, create client, connect
4. If SDK session file doesn't exist (pruned, moved), fall back to fresh client
5. Store in pool, return

**`set_model` flow (model change on live session):**
1. Look up `ManagedClient` for `(session_id, agent_name)`
2. If `active_run=True`, raise error (can't switch during active query)
3. Call `await managed_client.client.disconnect()`
4. Remove from pool
5. Next `get_or_create` call builds fresh client with new model in options

**Idle eviction:**
- Background `asyncio.Task` runs every 60s
- Iterates all pools, all clients
- If `active_run=False` and `monotonic() - last_activity > idle_timeout`: disconnect and remove
- Configurable timeout (default 600s / 10 min)
- Background dispatch clients get `immediate_teardown=True` flag — evicted as soon as run completes

### 2. `ManagedClient` — Wrapper dataclass

```python
@dataclass
class ManagedClient:
    client: ClaudeSDKClient
    session_id: str                     # Corvus session ID
    agent_name: str
    sdk_session_id: str | None          # From ResultMessage.session_id, for resume
    created_at: float                   # time.monotonic()
    last_activity: float                # Updated on every query
    active_run: bool                    # True while query() is in flight
    immediate_teardown: bool            # For background/cron dispatches
    options_snapshot: ClaudeAgentOptions # Frozen at creation time

    # Guardrails
    max_turns: int | None
    max_budget_usd: float | None
    fallback_model: str | None
    checkpointing_enabled: bool
    thinking_config: ThinkingConfig | None
    effort: str | None                  # "low" | "medium" | "high" | "max"

    # Accumulated metrics
    total_tokens: int
    total_cost_usd: float
    turn_count: int
    checkpoints: list[str]              # UserMessage UUIDs for rewind

    # Team membership
    team_name: str | None
```

**`options_snapshot` rationale:** Options are frozen at creation. If runtime state changes (model, permissions, break-glass), the client is torn down and rebuilt. This avoids drift between what the client was configured with and what Corvus thinks it should have.

**Metric accumulation:** After each `receive_response()` yields a `ResultMessage`, `ManagedClient` updates `total_tokens`, `total_cost_usd`, `turn_count`, and captures `sdk_session_id`. These feed the TUI status bar and session cost tracking without DB queries.

### 3. `StreamProcessor` — `corvus/gateway/stream_processor.py`

Translates raw SDK stream into Corvus protocol events.

```python
@dataclass
class RunContext:
    """All the IDs and metadata a stream processor needs to emit enriched events."""
    dispatch_id: str
    run_id: str
    task_id: str
    session_id: str
    turn_id: str
    agent_name: str
    model_id: str
    route_payload: dict                 # task_type, subtask_id, skill, instruction, route_index

@dataclass
class RunResult:
    """Outcome of processing a complete response stream."""
    status: str                         # "success" | "error" | "interrupted"
    tokens_used: int
    cost_usd: float
    context_pct: float
    response_text: str
    sdk_session_id: str | None
    checkpoints: list[str]


class StreamProcessor:
    def __init__(self, *, emitter: SessionEmitter, managed_client: ManagedClient):
        self._emitter = emitter
        self._client = managed_client
        self._text_buffer = ""
        self._tool_state: _ToolUseState | None = None
        self._thinking_buffer = ""

    async def process_response(self, ctx: RunContext) -> RunResult:
        """Consume the full response stream, emitting Corvus events as they arrive.

        Handles three message types:
        - StreamEvent: token-level deltas (text, tool input, thinking)
        - AssistantMessage: complete message blocks (fallback if StreamEvent missed)
        - ResultMessage: final result with usage/cost
        """
        async for message in self._client.client.receive_response():
            if isinstance(message, StreamEvent):
                await self._handle_stream_event(message, ctx)
            elif isinstance(message, AssistantMessage):
                await self._handle_assistant_message(message, ctx)
            elif isinstance(message, UserMessage):
                self._track_checkpoint(message)
            elif isinstance(message, ResultMessage):
                return self._finalize(message, ctx)
        # Should not reach here — ResultMessage terminates the stream
        return RunResult(status="error", ...)

    async def _handle_stream_event(self, event: StreamEvent, ctx: RunContext) -> None:
        raw = event.event
        is_subagent = event.parent_tool_use_id is not None

        match raw.get("type"):
            case "content_block_start":
                block = raw.get("content_block", {})
                block_type = block.get("type")
                if block_type == "text":
                    await self._emit(ctx, "text_stream_start", subagent=is_subagent)
                elif block_type == "tool_use":
                    self._tool_state = _ToolUseState(
                        name=block.get("name", ""),
                        id=block.get("id", ""),
                        input_buffer="",
                    )
                    await self._emit(ctx, "tool_start", tool=block.get("name"), subagent=is_subagent)
                elif block_type == "thinking":
                    await self._emit(ctx, "thinking_start", subagent=is_subagent)

            case "content_block_delta":
                delta = raw.get("delta", {})
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    text = delta.get("text", "")
                    self._text_buffer += text
                    await self._emit(ctx, "text_delta", content=text, subagent=is_subagent)
                elif delta_type == "input_json_delta":
                    if self._tool_state:
                        self._tool_state.input_buffer += delta.get("partial_json", "")
                elif delta_type == "thinking_delta":
                    text = delta.get("thinking", "")
                    self._thinking_buffer += text
                    await self._emit(ctx, "thinking_delta", content=text, subagent=is_subagent)

            case "content_block_stop":
                if self._tool_state:
                    await self._emit(ctx, "tool_complete",
                        tool=self._tool_state.name,
                        tool_input=self._tool_state.input_buffer,
                        subagent=is_subagent,
                    )
                    self._tool_state = None
                elif self._thinking_buffer:
                    await self._emit(ctx, "thinking_complete", subagent=is_subagent)
                    self._thinking_buffer = ""

    def _track_checkpoint(self, message: UserMessage) -> None:
        if message.uuid:
            self._client.checkpoints.append(message.uuid)

    def _finalize(self, result: ResultMessage, ctx: RunContext) -> RunResult:
        usage = getattr(result, "usage", None) or {}
        tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        cost = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
        # Update managed client metrics
        self._client.total_tokens += tokens
        self._client.total_cost_usd += cost
        self._client.turn_count += 1
        self._client.sdk_session_id = getattr(result, "session_id", None)
        self._client.active_run = False
        self._client.last_activity = time.monotonic()
        return RunResult(
            status="success",
            tokens_used=tokens,
            cost_usd=cost,
            response_text=self._text_buffer,
            sdk_session_id=self._client.sdk_session_id,
            checkpoints=list(self._client.checkpoints),
            ...
        )
```

### 4. `TeamContext` and team data structures

```python
@dataclass
class TeamContext:
    team_name: str
    session_id: str                         # Corvus session that owns this team
    members: dict[str, ManagedClient]       # agent_name -> client
    inbox_dir: Path                         # ~/.claude/teams/{team}/inboxes/
    task_dir: Path                          # ~/.claude/tasks/{team}/
    created_at: float
    inbox_monitor_task: asyncio.Task | None # Background watcher

@dataclass
class TeamMessage:
    from_agent: str
    to_agent: str | None                    # None = broadcast
    text: str
    summary: str
    timestamp: str                          # ISO-8601
    read: bool
    message_type: str                       # "message" | "broadcast" | "shutdown_request" | etc.

@dataclass
class TeamTask:
    id: str
    subject: str
    description: str
    status: str                             # "pending" | "in_progress" | "completed"
    owner: str | None
    blocked_by: list[str]
```

**Inbox monitoring:** Background `asyncio.Task` per team watches inbox JSON files for modifications (polling every 2s or `watchfiles` if available). New messages are:
1. Parsed into `TeamMessage`
2. Published through `runtime.emitter.emit("team_message", ...)`
3. Stored in Corvus's SessionManager event log for audit
4. Available for TUI rendering when surfaced

**Team-aware client creation:** When `get_or_create` builds a client and a `TeamContext` exists for that session, the `options_builder` callback injects:

```python
opts.env.update({
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_CODE_TEAM_NAME": team_context.team_name,
    "CLAUDE_CODE_AGENT_NAME": agent_name,
    "CLAUDE_CODE_AGENT_ID": str(uuid.uuid4()),
    "CLAUDE_CODE_AGENT_TYPE": agent_spec.metadata.get("team_type", "general-purpose"),
})
```

---

## Integration: How the New Flow Works

### Current flow (broken — `run_executor.py:295`)

```
User message
  → ChatEngine.resolve_chat_dispatch()
  → run_executor.execute_agent_run()
    → build_backend_options()           # builds ClaudeAgentOptions
    → async with ClaudeSDKClient() as client:  # ← NEW SUBPROCESS EVERY TIME
        → client.set_model(model)
        → client.query(message)
        → for msg in client.receive_response():
            if AssistantMessage: emit text chunks
            if ResultMessage: extract tokens
    # ← SUBPROCESS KILLED, ALL CONTEXT LOST
```

### New flow

```
User message
  → ChatEngine.resolve_chat_dispatch()
  → run_executor.execute_agent_run()
    → managed = sdk_manager.get_or_create(session_id, agent_name, options_builder)
        ← Returns EXISTING client (conversation continues from prior turns)
        ← OR creates new one (first message to this agent in this session)
        ← OR resumes from SDK session (reconnecting after process restart)
    → managed.active_run = True
    → sdk_manager.query(session_id, agent_name, prompt)
    → stream_processor = StreamProcessor(emitter, managed)
    → result = await stream_processor.process_response(run_context)
        → StreamEvent(text_delta) → emitter → WebSocket/TUI: character streams
        → StreamEvent(tool_start) → emitter → WebSocket/TUI: "Using Bash..."
        → StreamEvent(thinking_delta) → emitter → WebSocket/TUI: thinking visible
        → AssistantMessage → full block backup
        → ResultMessage → metrics, sdk_session_id captured
    → sdk_manager.release(session_id, agent_name)  # ← CLIENT STAYS ALIVE
    → Store sdk_session_id in SessionManager for future resume
```

### Background dispatch flow change

`background_dispatch.py` follows the same pattern but with `immediate_teardown=True`:

```python
managed = await sdk_manager.get_or_create(
    session_id, agent_name, options_builder,
)
managed.immediate_teardown = True  # one-shot, cleanup when done
# ... query, stream, release ...
# Idle eviction picks it up immediately after release
```

---

## Files Changed

| File | Change | Scope |
|------|--------|-------|
| `corvus/gateway/sdk_client_manager.py` | **NEW** | Full service: pool, lifecycle, all SDK features |
| `corvus/gateway/stream_processor.py` | **NEW** | StreamEvent → Corvus event translation |
| `corvus/gateway/run_executor.py` | **MAJOR** | Remove `ClaudeSDKClient` import, go through `sdk_manager` |
| `corvus/gateway/background_dispatch.py` | **MAJOR** | Same — remove direct SDK usage |
| `corvus/gateway/options.py` | **MODERATE** | Add `include_partial_messages=True`, `enable_file_checkpointing=True`, team env injection, `fallback_model`, `thinking`/`effort`, `max_turns`/`max_budget_usd` |
| `corvus/gateway/runtime.py` | **MINOR** | Add `sdk_client_manager: SDKClientManager` field |
| `corvus/gateway/chat_session.py` | **MINOR** | Pass `sdk_manager` to executor; expose `interrupt()` |
| `corvus/server.py` | **MINOR** | Initialize `SDKClientManager` in lifespan, `teardown_all()` on shutdown |
| `corvus/tui/protocol/in_process.py` | **MODERATE** | Use `sdk_manager` instead of building options/clients inline |
| `corvus/api/chat.py` | **MINOR** | Expose interrupt via `sdk_manager.interrupt()` |

## Files NOT Changed

| File | Why |
|------|-----|
| `corvus/security/policy.py` | Security stack untouched — `can_use_tool` callback still gates every tool |
| `corvus/hooks.py` | Hook creation unchanged — still passed to `ClaudeAgentOptions` |
| `corvus/permissions.py` | Permission evaluation unchanged |
| `corvus/gateway/chat_engine.py` | Routing logic unchanged — still decides which agent handles what |
| `corvus/gateway/task_planner.py` | Planning unchanged |
| `corvus/agents/hub.py` | Agent registry unchanged |
| `corvus/gateway/session_emitter.py` | Still the event sink — `StreamProcessor` feeds into it |
| `corvus/session.py` | `SessionTranscript` still tracks messages |

**Security invariants preserved:**
- `PolicyEngine` deny-wins-over-allow unchanged
- `can_use_tool` callback still gates every tool invocation on every SDK client
- `PreToolUse`/`PostToolUse` hooks still fire for audit and sanitization
- `ConfirmQueue` still blocks gated tools until user approves
- Workspace isolation still enforced per (session, agent) via `prepare_agent_workspace`
- Environment allowlist still filters subprocess env vars
- Audit log still captures all tool calls (allowed, denied, failed)

---

## Options Builder Pattern

The `options_builder` callback replaces static option construction. It captures runtime state at call time:

```python
# In run_executor.py — the builder closure
def make_options_builder(
    runtime, user, websocket, agent_name, ws_callback, session_id, confirm_queue,
    workspace_cwd, allow_secret_access, team_context,
):
    def builder() -> ClaudeAgentOptions:
        opts = build_backend_options(
            runtime=runtime, user=user, websocket=websocket,
            backend_name=backend_name, active_model=active_model,
            agent_name=agent_name, ws_callback=ws_callback,
            workspace_cwd=workspace_cwd, session_id=session_id,
            confirm_queue=confirm_queue,
            allow_secret_access=allow_secret_access,
        )
        # New SDK features — always enabled
        opts.include_partial_messages = True
        opts.enable_file_checkpointing = True

        # Guardrails from agent spec
        spec = runtime.agent_registry.get(agent_name)
        if spec and spec.metadata:
            opts.max_turns = spec.metadata.get("max_turns")
            opts.max_budget_usd = spec.metadata.get("max_budget_usd")
            opts.fallback_model = spec.metadata.get("fallback_model")
            effort = spec.metadata.get("effort")
            if effort in ("low", "medium", "high", "max"):
                opts.effort = effort

        # Team injection
        if team_context:
            opts.env.update({
                "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                "CLAUDE_CODE_TEAM_NAME": team_context.team_name,
                "CLAUDE_CODE_AGENT_NAME": agent_name,
                "CLAUDE_CODE_AGENT_ID": str(uuid.uuid4()),
            })

        return opts
    return builder
```

---

## Testing Strategy

**All tests behavioral — no mocks, per project policy (`CLAUDE.md`).**

### Unit-level (real objects, no subprocess)

| Test | What it verifies |
|------|-----------------|
| `test_managed_client_metrics` | Token/cost accumulation across multiple simulated ResultMessages |
| `test_idle_eviction` | Clients idle > timeout get disconnected; active clients survive |
| `test_pool_keying` | `(session_id, agent_name)` correctly isolates clients |
| `test_options_builder_injects_features` | `include_partial_messages`, `enable_file_checkpointing`, team env vars present |
| `test_model_change_tears_down_client` | `set_model()` disconnects existing client, pool entry removed |
| `test_team_context_env_injection` | Team env vars injected when team active, absent when not |

### Integration (real SDK subprocess)

| Test | What it verifies |
|------|-----------------|
| `test_persistent_context` | Send two queries to same client, second references first — context preserved |
| `test_interrupt_stops_generation` | Start long query, call `interrupt()`, verify stream stops |
| `test_stream_events_received` | With `include_partial_messages=True`, verify `StreamEvent` objects arrive before `AssistantMessage` |
| `test_session_resume` | Create client, query, disconnect, resume with `sdk_session_id`, verify context |
| `test_fork_session` | Fork session, verify forked and original are independent |
| `test_mcp_status` | Call `get_mcp_status()` on client with MCP servers, verify status dict |
| `test_file_checkpoint_rewind` | Enable checkpointing, make file change, capture checkpoint, rewind, verify file restored |
| `test_security_pipeline_with_persistent_client` | Verify `can_use_tool` fires on every tool call across multiple turns on same client |
| `test_concurrent_sessions` | Multiple sessions with different agents, verify isolation |

### QA / Manual validation

| Scenario | Steps |
|----------|-------|
| Multi-turn conversation | Send 5+ messages to same agent, verify it remembers context |
| Model switch mid-conversation | `/model` command, verify next response uses new model |
| Interrupt during tool execution | Start long Bash command, Ctrl+C, verify clean interrupt |
| Token-level streaming in TUI | Verify text appears character-by-character, tool status live |
| Session resume after TUI restart | Start conversation, quit TUI, restart, `/session resume`, verify context |
| Cost tracking accuracy | Compare `ManagedClient.total_cost_usd` with ResultMessage values |
| Idle timeout | Start conversation, wait 11 min, verify client disconnected, next message creates fresh |
| Background dispatch cleanup | Trigger webhook dispatch, verify client torn down immediately after completion |

---

## Execution Order

1. **`SDKClientManager` + `ManagedClient`** — core service with lifecycle management
2. **`StreamProcessor`** — event translation pipeline
3. **Rewire `run_executor.py`** — replace `async with ClaudeSDKClient` with `sdk_manager` calls
4. **Rewire `background_dispatch.py`** — same replacement
5. **Wire into `GatewayRuntime`** — initialization, shutdown
6. **Wire into `chat_session.py`** — pass through, expose interrupt
7. **Update `options.py`** — new feature flags, team injection
8. **Wire into `in_process.py`** — TUI path
9. **Add resume/fork support** — SDK session ID capture + resume flow
10. **Add team foundation** — `TeamContext`, env injection, inbox monitoring
11. **Integration tests** — real SDK subprocess tests
12. **QA validation** — manual multi-turn, streaming, interrupt, resume scenarios

---

## References

- [Anthropic Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python)
- [SDK Sessions Guide](https://platform.claude.com/docs/en/agent-sdk/sessions)
- [SDK Subagents Guide](https://platform.claude.com/docs/en/agent-sdk/subagents)
- [SDK Streaming Output Guide](https://platform.claude.com/docs/en/agent-sdk/streaming-output)
- [SDK File Checkpointing Guide](https://platform.claude.com/docs/en/agent-sdk/file-checkpointing)
- [SDK Hooks Guide](https://platform.claude.com/docs/en/agent-sdk/hooks)
- [SDK MCP Integration Guide](https://platform.claude.com/docs/en/agent-sdk/mcp)
- [Claude Code Agent Teams Docs](https://code.claude.com/docs/en/agent-teams)
- [Building Agents with the Claude Agent SDK (Blog)](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)
- [claude-agent-sdk-python (GitHub)](https://github.com/anthropics/claude-agent-sdk-python)
- [claude-agent-sdk-demos (GitHub)](https://github.com/anthropics/claude-agent-sdk-demos)
- [claude-agent-sdk (PyPI)](https://pypi.org/project/claude-agent-sdk/)
- [ruflo — Enterprise multi-agent orchestration](https://github.com/ruvnet/ruflo)
- [ccswarm — Rust-native agent coordination](https://github.com/nwiizo/ccswarm)
- [claude-agent-sdk-mastery — Learning resource](https://github.com/kokevidaurre/claude-agent-sdk-mastery)
- [awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)
- [claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability)

---

## Current Corvus Files Referenced

- `corvus/gateway/run_executor.py:295` — Current throwaway `async with ClaudeSDKClient` pattern
- `corvus/gateway/background_dispatch.py:350` — Same throwaway pattern for background dispatch
- `corvus/gateway/options.py:168-243` — `build_options()` and `build_backend_options()` — option construction
- `corvus/gateway/options.py:265-347` — `_build_can_use_tool()` — permission callback (unchanged)
- `corvus/gateway/options.py:130-165` — `build_hooks()` — hook construction (unchanged)
- `corvus/gateway/chat_session.py:83-398` — `ChatSession` — session lifecycle
- `corvus/gateway/runtime.py` — `GatewayRuntime` — new `sdk_client_manager` field
- `corvus/server.py` — Lifespan initialization
- `corvus/tui/protocol/in_process.py` — TUI in-process gateway
- `corvus/api/chat.py` — WebSocket chat endpoint
- `corvus/gateway/workspace_runtime.py` — Workspace lifecycle (already fixed)
