# Corvus TUI Design — Rich + prompt_toolkit CLI

**Date:** 2026-03-08
**Status:** Approved
**Summary:** Full-parity CLI chat experience using Python (Rich + prompt_toolkit). Replaces the current Claude CLI wrapper. Serves as the proving ground for the WebSocket protocol that the SvelteKit frontend will also consume.

---

## Goals

1. Full feature parity with the planned SvelteKit frontend
2. Multi-agent orchestration as a first-class feature (not bolted on)
3. Recursive subagent navigation — enter/exit agent contexts like a directory stack
4. Resume conversations across sessions
5. System-level commands handled natively (no agent/token cost)
6. DRY, class-based, minimal architecture
7. Same WebSocket protocol as the frontend (in-process v1, WebSocket v2)

## Non-Goals

- Animated graphics, image rendering, or terminal art (save for frontend)
- Replacing the SvelteKit frontend (this is a parallel surface, not a replacement)
- Go, Rust, or Node.js dependencies

---

## Architecture

### Stack

- **Input:** prompt_toolkit (editor, keybindings, completions, layout)
- **Output:** Rich (markdown, syntax highlighting, tables, panels, streaming)
- **Backend:** Corvus gateway (in-process v1, WebSocket v2)
- **Entry point:** `uv run python -m corvus.tui` / `mise run tui`

### Module Structure

```
corvus/tui/
├── app.py                  # TuiApp — main entry, event loop, lifecycle
├── layout.py               # TerminalLayout — prompt_toolkit layout composition
├── theme.py                # Colors, styles, agent color assignments
│
├── core/
│   ├── agent_stack.py      # AgentStack — recursive push/pop agent navigation
│   ├── session.py          # SessionManager — create, resume, list, search, export
│   ├── command_router.py   # CommandRouter — tier-based input dispatch
│   └── event_handler.py    # EventHandler — maps protocol events to render calls
│
├── input/
│   ├── editor.py           # ChatEditor — multi-line input, vi/emacs bindings
│   ├── completer.py        # ChatCompleter — @agent, /command, !tool completions
│   └── parser.py           # InputParser — parse @mentions, /commands, !tools
│
├── output/
│   ├── renderer.py         # ChatRenderer — Rich console into prompt_toolkit buffer
│   ├── stream.py           # StreamHandler — token-by-token markdown rendering
│   ├── tool_view.py        # ToolCallView — collapsible tool call display
│   └── token_counter.py    # TokenCounter — per-message, session, cost tracking
│
├── screens/
│   ├── chat.py             # ChatScreen — main chat interface
│   ├── setup.py            # SetupScreen — setup wizard, credential dashboard
│   ├── agents.py           # AgentScreen — browse, create, edit agents
│   ├── sessions.py         # SessionScreen — history browser with search
│   ├── memory.py           # MemoryScreen — memory hub search/browse
│   ├── tools.py            # ToolScreen — tool browser, history, direct invoke
│   └── workers.py          # WorkerScreen — subagent panel, status, output
│
├── panels/
│   ├── sidebar.py          # SidebarPanel — toggleable tree panel with sections
│   └── sections.py         # CollapsibleSection, AgentTree, WorkerTree, etc.
│
├── commands/
│   ├── registry.py         # CommandRegistry — register/lookup slash commands
│   ├── builtins.py         # Built-in commands (/agents, /tools, /sessions, etc.)
│   └── domain.py           # DomainCommands — per-agent commands from agent.yaml
│
└── protocol/
    ├── base.py             # GatewayProtocol — abstract interface
    ├── in_process.py       # InProcessGateway — direct gateway import (v1)
    ├── websocket.py        # WebSocketGateway — WS client (v2)
    └── events.py           # Event types (matches existing WS protocol exactly)
```

---

## Core Classes

### AgentStack — Recursive Agent Navigation

The central abstraction. Agents are a stack, not a flat selection. You can enter a subagent, then enter its subagent, then pop back up. Like `cd` into directories.

```python
class AgentContext:
    """A single frame in the agent stack."""
    agent_name: str
    session_id: str
    display_name: str
    parent: AgentContext | None
    children: list[AgentContext]      # spawned subagents
    token_count: int
    status: AgentStatus               # idle, thinking, executing, waiting

class AgentStack:
    """Recursive agent navigation. Push to enter, pop to return."""

    def __init__(self):
        self._stack: list[AgentContext] = []

    @property
    def current(self) -> AgentContext:
        """The agent the user is currently talking to."""
        return self._stack[-1]

    @property
    def depth(self) -> int:
        return len(self._stack)

    @property
    def breadcrumb(self) -> str:
        """e.g. 'work > codex > researcher'"""
        return " > ".join(ctx.agent_name for ctx in self._stack)

    def push(self, agent_name: str, session_id: str) -> AgentContext:
        """Enter a subagent context."""

    def pop(self) -> AgentContext:
        """Return to parent agent. Raises if at root."""

    def pop_to_root(self) -> AgentContext:
        """Return to top-level agent."""

    def switch(self, agent_name: str, session_id: str):
        """Switch root agent (clears stack, starts fresh)."""
```

**Usage flow:**
```
User starts talking to @work          → stack: [work]
work spawns codex subagent            → stack: [work, codex]
User: /enter codex                    → now talking to codex directly
codex spawns researcher               → stack: [work, codex, researcher]
User: /back                           → stack: [work, codex]
User: /back                           → stack: [work]
User: /top                            → stack: [work] (already at root)
User: /agent homelab                  → stack: [homelab] (switch root)
```

### CommandRouter — Three-Tier Input Dispatch

```python
class InputTier(Enum):
    SYSTEM = "system"       # TUI handles directly, no gateway
    SERVICE = "service"     # TUI calls a Corvus service (memory, sessions, etc.)
    AGENT = "agent"         # Routed to agent via gateway protocol

class CommandRouter:
    """Routes parsed input to the correct handler tier."""

    def route(self, parsed: ParsedInput) -> InputTier:
        """Determine which tier handles this input."""

    async def dispatch(self, parsed: ParsedInput):
        """Route and execute."""
```

**Tier assignments:**

| Tier | Commands |
|------|----------|
| SYSTEM | `/setup`, `/agents new`, `/agent edit`, `/models`, `/model`, `/breakglass`, `/reload`, `/config`, `/quit`, `/help`, `/focus`, `/split`, `/theme` |
| SERVICE | `/memory`, `/sessions`, `/session resume`, `/tools`, `/tool-history`, `/view`, `/edit`, `/diff`, `/workers`, `/tokens`, `/status`, `/export` |
| AGENT | Plain text, `@mentions`, `/summon`, `/spawn`, `/enter`, `/back`, `/top`, `!tool` calls |

### GatewayProtocol — Swappable Backend

```python
class GatewayProtocol(ABC):
    """Abstract interface to Corvus gateway. Same for in-process and WebSocket."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_message(
        self,
        text: str,
        target_agent: str | None = None,
        target_agents: list[str] | None = None,
        dispatch_mode: str = "router",
        model: str | None = None,
    ) -> str: ...  # returns dispatch_id

    @abstractmethod
    async def respond_confirm(self, confirm_id: str, approved: bool) -> None: ...

    @abstractmethod
    async def cancel_run(self, run_id: str) -> None: ...

    @abstractmethod
    async def list_sessions(self) -> list[SessionSummary]: ...

    @abstractmethod
    async def resume_session(self, session_id: str) -> SessionDetail: ...

    @abstractmethod
    def on_event(self, callback: Callable[[ProtocolEvent], Awaitable[None]]) -> None: ...
```

### SessionManager — Resume & History

```python
class SessionManager:
    """Manages chat sessions — create, resume, list, search, export."""

    async def create(self, agent_name: str) -> str:
        """Create new session, return session_id."""

    async def resume(self, session_id: str) -> SessionDetail:
        """Load session history, restore agent stack state."""

    async def list_sessions(
        self,
        agent: str | None = None,
        limit: int = 20,
    ) -> list[SessionSummary]: ...

    async def search(self, query: str) -> list[SessionSummary]:
        """Full-text search across session history."""

    async def export(self, session_id: str, path: str) -> str:
        """Export session to markdown file."""

    async def current_session_id(self) -> str: ...
```

### ChatRenderer — Output Rendering

```python
class ChatRenderer:
    """Renders protocol events into Rich output in the chat pane."""

    def render_user_message(self, text: str, agent: str) -> None: ...
    def render_agent_message(self, agent: str, text: str, tokens: int) -> None: ...
    def render_stream_chunk(self, agent: str, chunk: str, final: bool) -> None: ...
    def render_tool_start(self, tool_name: str, params: dict) -> None: ...
    def render_tool_result(self, tool_name: str, result: Any, collapsed: bool) -> None: ...
    def render_confirm_prompt(self, confirm_id: str, tool: str, params: dict) -> None: ...
    def render_error(self, error: str) -> None: ...
    def render_system(self, text: str) -> None: ...
    def render_breadcrumb(self, stack: AgentStack) -> None: ...
```

---

## UI Layout

### Default Layout

```
┌─ Breadcrumb ──────────────────────────────────────────┐
│ work > codex                                          │
├─ Status ──────────────────────────────────────────────┤
│ @codex │ opus │ ⚡1 worker │ 45.1k tok │ $0.22       │
├───────────────────────────────────────────────────────┤
│                                                       │
│  You: fix the auth bug in src/auth.py                 │
│                                                       │
│  codex: Looking at the auth module...                 │
│                                                       │
│  ┌─ Read("src/auth.py") ──────────────── ▼ collapse ─┐│
│  │ 1│ import jwt                                     ││
│  │ 2│ from datetime import datetime                  ││
│  │ ...                                               ││
│  └───────────────────────────────────────────────────┘│
│                                                       │
│  codex: Found the issue. The token expiry check       │
│  compares against UTC but `created_at` is local...    │
│                                                       │
│  ┌─ Edit("src/auth.py") ─────────────── [y/n/always] ┐│
│  │ - if token.exp < datetime.now():                  ││
│  │ + if token.exp < datetime.now(timezone.utc):      ││
│  └───────────────────────────────────────────────────┘│
│                                                       │
├───────────────────────────────────────────────────────┤
│ > █                                    Ctrl+D to send │
│                                        Alt+Enter new  │
│   @agent  /command  !tool  /back                      │
└───────────────────────────────────────────────────────┘
```

### Split Mode

```
┌─ Status ──────────────────────────────────────────────┐
│ SPLIT: @homelab + @finance │ 18.2k tok │ $0.05       │
├──────────────────────────┬────────────────────────────┤
│ homelab                  │ finance                    │
│                          │                            │
│ Nginx errors cleared.    │ Q3 looks strong.           │
│ Restarted upstream pool. │ Revenue: $142k (+12%)      │
│                          │                            │
├──────────────────────────┴────────────────────────────┤
│ > @all how are things looking?                        │
└───────────────────────────────────────────────────────┘
```

### Worker Panel

```
┌─ Status ──────────────────────────────────────────────┐
│ @work │ opus │ ⚡2 workers │ 45.1k tok                │
├─────────────────────────────────┬─────────────────────┤
│ Chat                            │ Workers             │
│                                 │                     │
│ work: Spawned two subagents.    │ codex [executing]   │
│                                 │  fixing auth.py     │
│ Type /enter codex to jump in.   │  12.4k tok          │
│                                 │                     │
│                                 │ researcher [idle]   │
│                                 │  API docs fetched   │
│                                 │  3.1k tok           │
│                                 │                     │
│                                 │ [/enter] [/kill]    │
├─────────────────────────────────┴─────────────────────┤
│ > █                                                   │
└───────────────────────────────────────────────────────┘
```

### Pop-Out Tree Panel (Sidebar)

Inspired by Harlequin's collapsible sidebar and Toad's tree+sections pattern. The sidebar is a **toggleable panel** (Ctrl+B or `/panel`) that slides in from the right, taking 25-30% of terminal width (max 45%). Contains collapsible tree sections.

```
┌─ Status ────────────────────────────────┬─────────────┐
│ @work │ opus │ 45.1k tok               │ ▼ Agents    │
├─────────────────────────────────────────│  work ●     │
│                                         │  homelab    │
│  You: fix the auth bug                  │  finance    │
│                                         │  personal   │
│  work: Looking at auth module...        │  docs       │
│                                         │  inbox      │
│  ┌─ Read("src/auth.py") ──── ▼ ──────┐ │             │
│  │ import jwt                        │ │ ▼ Workers   │
│  │ from datetime import datetime     │ │  └ codex    │
│  └───────────────────────────────────┘ │    [running] │
│                                         │  └ researcher│
│  work: Found the issue...               │    [idle]   │
│                                         │             │
│                                         │ ▶ Sessions  │
│                                         │ ▶ Memory    │
├─────────────────────────────────────────┴─────────────┤
│ > █                                                   │
└───────────────────────────────────────────────────────┘
```

**Sidebar sections (collapsible with ▼/▶):**

| Section | Content | Tree Structure |
|---------|---------|---------------|
| **Agents** | All available agents, active one marked `●` | Flat list, active highlighted |
| **Workers** | Subagents of current agent | Tree: agent → children, with status badges |
| **Sessions** | Recent chat sessions | Flat list, newest first, truncated preview |
| **Memory** | Recent memory entries | Flat list, tag-grouped |

**Implementation:** Rich `Tree()` for hierarchical views, `Panel()` for sections, toggle via `display: none` pattern (Harlequin). The sidebar is a `prompt_toolkit` `HSplit`/`VSplit` container that can be shown/hidden.

**Keybindings:**
- `Ctrl+B` — Toggle sidebar
- `Ctrl+1` through `Ctrl+4` — Jump to sidebar section (agents/workers/sessions/memory)
- `Enter` on sidebar item — activate (switch agent, enter worker, resume session)
- `Escape` — close sidebar, return focus to chat

**Module:** `corvus/tui/panels/sidebar.py`

```python
class SidebarPanel:
    """Toggleable tree panel with collapsible sections."""

    visible: bool = False
    sections: list[CollapsibleSection]

    def toggle(self) -> None:
        """Show/hide sidebar."""
        self.visible = not self.visible

    def render(self) -> Panel:
        """Render all sections into a Rich Panel."""
        ...

class CollapsibleSection:
    """A sidebar section with ▼/▶ toggle."""
    title: str
    expanded: bool
    items: list[SidebarItem]

    def toggle(self) -> None:
        self.expanded = not self.expanded

    def render_tree(self) -> Tree:
        """Render items as a Rich Tree."""
        ...

class AgentTreeSection(CollapsibleSection):
    """Shows all agents with active marker."""
    ...

class WorkerTreeSection(CollapsibleSection):
    """Shows subagent hierarchy with status badges."""
    ...

class SessionListSection(CollapsibleSection):
    """Shows recent sessions with previews."""
    ...

class MemoryListSection(CollapsibleSection):
    """Shows recent memories grouped by tag."""
    ...
```

---

## Input Parsing

```python
class ParsedInput:
    """Result of parsing user input."""
    raw: str
    kind: Literal["command", "tool_call", "mention", "chat"]
    command: str | None          # e.g. "agents", "memory search"
    command_args: str | None     # e.g. "homelab", '"search query"'
    tool_name: str | None       # e.g. "obsidian.search"
    tool_params: dict | None    # parsed from input
    mentions: list[str]         # e.g. ["homelab", "finance"]
    text: str                   # the actual message text (mentions stripped)
```

**Parse rules (evaluated in order):**

1. `/command args...` → `kind="command"`
2. `!tool.name params...` → `kind="tool_call"`
3. `@agent message` → `kind="mention"`, extract mentions + text
4. Everything else → `kind="chat"`, send to current agent

---

## Agent Navigation Commands

| Command | Action | Stack Effect |
|---------|--------|-------------|
| `/agent <name>` | Switch root agent | Clears stack, pushes new root |
| `/spawn <name> "task"` | Spawn subagent | Adds child to current context |
| `/enter <name>` | Enter subagent | Pushes onto stack |
| `/back` | Return to parent | Pops stack |
| `/top` | Return to root | Pops to root |
| `/summon <name>` | Temporary coworker | Pushes agent, auto-pops when done |
| `/workers` | Toggle worker panel | Shows/hides spawned subagents |
| `/kill <name>` | Kill subagent | Terminates process, removes from children |

---

## Slash Command Registry

```python
class SlashCommand:
    """A registered slash command."""
    name: str
    description: str
    tier: InputTier
    handler: Callable
    args_spec: str | None       # e.g. "<agent_name>", '"query"'
    agent_scoped: bool          # only available for specific agents

class CommandRegistry:
    """Central registry for all slash commands."""

    def register(self, command: SlashCommand) -> None: ...
    def lookup(self, name: str) -> SlashCommand | None: ...
    def completions(self, partial: str) -> list[str]: ...
    def commands_for_agent(self, agent: str) -> list[SlashCommand]: ...
    def all_commands(self) -> list[SlashCommand]: ...
```

**Built-in commands (always available):**

```
/help                    Show all commands
/quit                    Exit TUI
/agents                  List all agents with status
/agent <name>            Switch to agent
/agent new               Create new agent (wizard)
/agent edit <name>       Edit agent config in $EDITOR
/models                  List available models
/model <name>            Switch model for current agent
/sessions                Browse session history
/session new             Start new session
/session resume <id>     Resume past session
/sessions search "q"     Search session history
/memory search "q"       Search memory hub
/memory list             Browse recent memories
/memory add "fact"       Add manual memory
/tools                   List tools for current agent
/tool <name>             Tool detail + usage
/tool-history            Recent tool calls
/view <path>             View file with syntax highlighting
/edit <path>             Open file in $EDITOR
/diff <path>             Show file diff
/spawn <name> "task"     Spawn subagent
/enter <name>            Enter subagent context
/back                    Return to parent agent
/top                     Return to root agent
/summon <name>           Temporary coworker
/workers                 Toggle worker panel
/kill <name>             Kill subagent
/breakglass              Elevate permissions
/setup                   Run setup wizard
/setup status            Credential dashboard
/reload                  Hot-reload configs
/tokens                  Token usage details
/status                  System status
/focus                   Toggle focus mode
/split                   Toggle split mode
/panel                   Toggle sidebar tree panel
/export                  Export session to markdown
/theme <name>            Switch color theme
```

---

## Session Resume

Sessions persist to SQLite. Resuming restores:

1. **Conversation history** — all messages, tool calls, results
2. **Agent stack state** — which agent was active, any subagent depth
3. **Token counts** — running totals
4. **Active model** — per-agent model assignments

```python
class SessionDetail:
    session_id: str
    created_at: datetime
    updated_at: datetime
    agent_stack: list[str]          # serialized stack state
    messages: list[SessionMessage]
    total_tokens: int
    model: str

class SessionMessage:
    role: Literal["user", "assistant", "tool_call", "tool_result", "system"]
    agent: str
    content: str
    timestamp: datetime
    tokens: int | None
    tool_name: str | None
    tool_params: dict | None
    collapsed: bool                 # for tool results in replay
```

---

## Protocol Events

Matches the existing WebSocket protocol exactly. The TUI's `EventHandler` maps these to `ChatRenderer` calls:

```python
class ProtocolEvent:
    """Base event from gateway."""
    type: str
    timestamp: datetime

class DispatchStart(ProtocolEvent):       type = "dispatch_start"
class DispatchPlan(ProtocolEvent):        type = "dispatch_plan"
class RunStart(ProtocolEvent):            type = "run_start"
class RunPhase(ProtocolEvent):            type = "run_phase"
class RunOutputChunk(ProtocolEvent):      type = "run_output_chunk"
class ToolStart(ProtocolEvent):           type = "tool_start"
class ToolResult(ProtocolEvent):          type = "tool_result"
class ConfirmRequest(ProtocolEvent):      type = "confirm_request"
class ConfirmResponse(ProtocolEvent):     type = "confirm_response"
class RunComplete(ProtocolEvent):         type = "run_complete"
class DispatchComplete(ProtocolEvent):    type = "dispatch_complete"
```

---

## Completions

prompt_toolkit completions trigger on:

| Prefix | Completes | Source |
|--------|-----------|-------|
| `@` | Agent names | Agent registry |
| `/` | Slash commands | CommandRegistry (filtered by current agent) |
| `!` | Tool names | Tool registry for current agent |
| `/session resume ` | Session IDs | Recent sessions |
| `/model ` | Model names | Model registry |
| `/agent ` | Agent names | Agent registry |
| `/enter ` | Active subagent names | Current context's children |
| `/view ` `/edit ` | File paths | Filesystem completion |

---

## Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+D` or `Enter` (single-line) | Send message |
| `Alt+Enter` | New line in editor |
| `Ctrl+C` | Cancel active run |
| `Ctrl+L` | Clear screen |
| `Ctrl+R` | Search history |
| `Ctrl+P` / `Ctrl+N` | Previous/next in history |
| `Ctrl+B` | Toggle sidebar panel |
| `Ctrl+T` | Toggle split mode |
| `Ctrl+1` | Jump to Agents section (sidebar) |
| `Ctrl+2` | Jump to Workers section (sidebar) |
| `Ctrl+3` | Jump to Sessions section (sidebar) |
| `Ctrl+4` | Jump to Memory section (sidebar) |
| `Escape` | `/back` (pop agent stack) |
| `Tab` | Accept completion |
| `F1` | Help |

---

## Theme System

Each agent gets a consistent color across the UI:

```python
AGENT_COLORS = {
    "huginn": "bright_magenta",
    "work": "bright_blue",
    "homelab": "bright_green",
    "finance": "bright_yellow",
    "personal": "bright_cyan",
    "music": "bright_red",
    "docs": "bright_white",
    "inbox": "orange1",
}
```

Themes define: background, foreground, accent, border, muted, error, warning, success. Ship with at least: `default` (dark), `light`, `minimal`.

---

## Implementation Phases

### Phase 1: Core Chat Loop
- `TuiApp`, `TerminalLayout`, `ChatEditor`, `ChatRenderer`
- `InputParser`, `CommandRouter` (system tier only)
- `InProcessGateway` (direct gateway import)
- Single agent chat with streaming markdown
- Basic `/agents`, `/agent`, `/quit`, `/help`

### Phase 2: Multi-Agent & Sessions
- `AgentStack` with push/pop/switch
- `SessionManager` — create, resume, list
- `@mention` parsing and dispatch
- `/spawn`, `/enter`, `/back`, `/top`
- Worker panel
- Token counter in status bar

### Phase 3: Tools & Commands
- `CommandRegistry` with full built-in set
- `ChatCompleter` for @, /, ! completions
- `ToolCallView` with collapsible display
- Confirm/deny flow
- Direct `!tool` invocation
- `/memory`, `/tools`, `/view`, `/edit`, `/diff`

### Phase 4: System Screens
- `SetupScreen` — replaces current setup wizard
- `AgentScreen` — create/edit agents
- `SessionScreen` — history browser with search
- `MemoryScreen` — memory hub browser

### Phase 5: Polish & Production
- `WebSocketGateway` (v2 protocol backend)
- Split mode
- Theme system
- `/breakglass`
- `/export`
- Session search (FTS5)
- Domain-scoped slash commands from agent.yaml
- Keybinding customization

---

## Dependencies

```toml
[project.dependencies]
prompt-toolkit = ">=3.0"
rich = ">=13.0"
```

No other TUI dependencies. Both are mature, well-maintained, and already widely used together.

---

## Entry Points

```toml
[project.scripts]
corvus-tui = "corvus.tui.app:main"
```

```toml
# mise.toml
[tasks.tui]
run = "uv run python -m corvus.tui"
description = "Start Corvus TUI"
```

---

## Security Integration

The TUI must respect the `corvus/security/` architecture. No shortcuts.

### Authentication

- **No localhost auto-auth.** `SessionAuthManager` requires HMAC-SHA256 session tokens or trusted proxy headers.
- **InProcessGateway (v1):** Bypasses WebSocket auth — runs in-process, no token needed.
- **WebSocketGateway (v2):** Must obtain a session token (from `CORVUS_SESSION_SECRET` env or interactive login) and send it as a query param or Authorization header.
- Add `/login` command for token-based auth when using WebSocket mode.

### Permission Tiers

- TUI displays the current permission tier in the status bar: `strict`, `default`, or `break_glass`.
- Confirm/deny prompts should show tier context — in break-glass mode, default is "allow."
- `PolicyEngine.compose_deny_list()` determines what tools are denied per tier.

### Break-Glass Mode

`/breakglass` is NOT a simple flag toggle:
1. Requires authenticated user
2. Creates session-bound HMAC token via `create_break_glass_token()`
3. Token has TTL (default 1h, max 4h from `config/policy.yaml`)
4. Status bar shows `BREAK-GLASS [47m remaining]` with countdown
5. Auto-deactivates after 30min idle via `SessionTimeoutTracker`
6. Global deny list (`*.env*`, `*.key`, etc.) STILL applies — break-glass is not god mode

### Tool Call Security Pipeline

Every tool call flows through:
```
1. ToolContext.permissions.is_denied(tool_name)  → PolicyEngine deny list
2. SlidingWindowRateLimiter.check()              → 10 mutations/min, 60 reads/min
3. ToolContext.permissions.is_confirm_gated()     → requires user approval
4. MCPToolDef.execute(ctx, **params)             → only declared credentials injected
5. sanitize_tool_result(output)                  → scrub secrets before display
6. AuditLog.log_tool_call()                      → JSONL audit trail
```

The TUI must:
- Render rate limit denials with `retry_after_seconds`
- Never display unsanitized tool results
- Show audit trail via `/audit` command

### New Commands (Security)

| Command | Tier | Description |
|---------|------|-------------|
| `/breakglass` | SYSTEM | Activate break-glass mode with TTL |
| `/breakglass off` | SYSTEM | Deactivate break-glass |
| `/audit` | SERVICE | Show recent audit log entries |
| `/audit <agent>` | SERVICE | Filter audit by agent |
| `/policy` | SERVICE | Show current permission tier and deny patterns |
| `/login` | SYSTEM | Authenticate for WebSocket mode |

---

## Key Design Principles

1. **DRY** — one `AgentStack`, one `CommandRouter`, one `GatewayProtocol`. No duplication.
2. **Class-based** — clear responsibilities per class. No god objects.
3. **Recursive** — `AgentStack` supports infinite depth. Same code handles root and sub-sub-subagent.
4. **Protocol-first** — TUI speaks the same protocol as the frontend. Build once, render twice.
5. **Tiered dispatch** — system commands never burn tokens. Service queries never need an agent.
6. **Swappable backend** — in-process for dev, WebSocket for production. Same interface.
7. **Security-first** — all tool calls go through PolicyEngine + RateLimiter + Sanitizer. No bypass.
8. **No lazy imports** — all dependencies resolved at module load.
9. **No mocks in tests** — test with real prompt_toolkit apps, real Rich output, real sessions.
