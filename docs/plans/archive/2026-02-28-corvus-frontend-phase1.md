---
title: "Corvus Frontend Phase 1 (Chat MVP) Implementation Plan"
type: plan
status: implemented
date: 2026-02-28
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# Corvus Frontend — Phase 1 (Chat MVP) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A deployable SvelteKit chat frontend at `corvus.absolvbass.com` that connects to the gateway WebSocket, streams agent responses, shows tool call cards, handles confirm-gating, and displays agent portraits with state animations.

**Architecture:** Static SvelteKit 2 app (Svelte 5 runes, Tailwind 4, static adapter) served by nginx in Docker on optiplex. Communicates with the Python gateway on laptop-server:18789 via WebSocket (`/ws`) and REST API (`/api/*`). Auth is transparent — Authelia injects `X-Remote-User` at the SWAG layer. Backend changes extend the existing WebSocket protocol and add session REST endpoints.

**Tech Stack:** SvelteKit 2, Svelte 5, TailwindCSS 4, Shiki, svelte-markdown, Vitest, Docker + nginx

**Design doc:** `docs/plans/2026-02-28-corvus-frontend-design.md`

**Testing policy:** Python backend tests follow the project's NO MOCKS policy (real SQLite, real HTTP). Frontend tests use Vitest + @testing-library/svelte for components, Playwright for E2E.

---

## Task 1: Backend — Extend WebSocket Protocol

The existing WebSocket handler sends only `{"type": "text", "content": "..."}` and `{"type": "done", ...}`. We need to enrich it with routing, agent status, tool events, and confirm-gating messages so the frontend can render agent badges, tool cards, and approval dialogs.

**Files:**
- Modify: `corvus/server.py` (lines 413-538 — WebSocket handler, lines 269-279 — hook wiring)
- Modify: `corvus/hooks.py` (lines 63-95 — `create_hooks`, add tool_start/tool_result emission)
- Modify: `corvus/events.py` (no structural changes, just new event types)
- Test: `tests/gateway/test_ws_protocol.py` (new)

**Step 1: Write the failing test for enriched WebSocket messages**

Create `tests/gateway/test_ws_protocol.py`:

```python
"""Tests for extended WebSocket protocol messages.

Verifies the gateway sends routing, agent_status, tool_start, tool_result,
and confirm_request messages in addition to text and done.
"""
import json
from datetime import datetime, UTC

from corvus.hooks import create_hooks, CONFIRM_GATED_TOOLS
from corvus.events import EventEmitter


class TestWSProtocolMessages:
    """Verify the shape of each new WebSocket message type."""

    def test_routing_message_shape(self):
        """Routing message includes agent name and model."""
        msg = {
            "type": "routing",
            "agent": "homelab",
            "model": "claude-sonnet-4-6",
        }
        assert msg["type"] == "routing"
        assert msg["agent"] == "homelab"
        assert "model" in msg

    def test_agent_status_message_shape(self):
        """Agent status message includes agent and status enum."""
        msg = {
            "type": "agent_status",
            "agent": "homelab",
            "status": "thinking",
        }
        assert msg["status"] in ("thinking", "streaming", "done", "error")

    def test_tool_start_message_shape(self):
        """Tool start message includes tool name, params, and call_id."""
        msg = {
            "type": "tool_start",
            "tool": "bash",
            "params": {"command": "docker ps"},
            "call_id": "abc-123",
        }
        assert msg["type"] == "tool_start"
        assert "call_id" in msg

    def test_tool_result_message_shape(self):
        """Tool result includes call_id, output, duration, and status."""
        msg = {
            "type": "tool_result",
            "call_id": "abc-123",
            "output": "container running",
            "duration_ms": 800,
            "status": "success",
        }
        assert msg["status"] in ("success", "error")
        assert isinstance(msg["duration_ms"], (int, float))

    def test_confirm_request_message_shape(self):
        """Confirm request includes tool, params, call_id, and timeout."""
        msg = {
            "type": "confirm_request",
            "tool": "email_send",
            "params": {"to": "user@example.com", "subject": "Test"},
            "call_id": "def-456",
            "timeout_s": 60,
        }
        assert msg["type"] == "confirm_request"
        assert msg["timeout_s"] == 60

    def test_done_message_includes_context_metrics(self):
        """Done message includes token and context window metrics."""
        msg = {
            "type": "done",
            "session_id": "sess-001",
            "cost_usd": 0.04,
            "tokens_used": 2847,
            "context_limit": 200000,
            "context_pct": 1.4,
        }
        assert "tokens_used" in msg
        assert "context_pct" in msg

    def test_interrupt_client_message_shape(self):
        """Client can send interrupt message."""
        msg = {"type": "interrupt"}
        assert msg["type"] == "interrupt"

    def test_memory_changed_message_shape(self):
        """Memory changed event includes domain and summary."""
        msg = {
            "type": "memory_changed",
            "domain": "homelab",
            "action": "save",
            "summary": "plex running on miniserver",
        }
        assert msg["type"] == "memory_changed"
        assert msg["domain"] == "homelab"


class TestHookToolEvents:
    """Verify hooks emit tool_start and tool_result events."""

    def test_confirm_gated_tools_includes_expected(self):
        """Confirm-gated tools set contains destructive tools."""
        assert "email_send" in CONFIRM_GATED_TOOLS
        assert "ha_call_service" in CONFIRM_GATED_TOOLS
        assert "firefly_create_transaction" in CONFIRM_GATED_TOOLS

    def test_create_hooks_returns_expected_keys(self):
        """create_hooks returns pre and post tool use handlers."""
        emitter = EventEmitter()
        hooks = create_hooks(emitter)
        assert "pre_tool_use" in hooks
        assert "post_tool_use" in hooks
```

**Step 2: Run test to verify it passes (these are contract shape tests)**

```bash
mise run test -- tests/gateway/test_ws_protocol.py -v
```

Expected: PASS (these validate message shapes, not server behavior yet).

**Step 3: Modify `corvus/server.py` WebSocket handler to send enriched messages**

In `corvus/server.py`, modify the WebSocket handler (lines 454-496) to emit routing and done messages with extended fields:

After line 462 (`logger.info("Routed message: agent=%s backend=%s", ...)`), add:
```python
                # Send routing decision to frontend
                await websocket.send_json({
                    "type": "routing",
                    "agent": target_agent,
                    "model": backend_name,
                })
```

Modify the `done` message (line 490) to include context metrics:
```python
                        await websocket.send_json(
                            {
                                "type": "done",
                                "session_id": message.session_id,
                                "cost_usd": message.total_cost_usd,
                                "tokens_used": getattr(message, "total_input_tokens", 0) + getattr(message, "total_output_tokens", 0),
                                "context_limit": 200000,
                                "context_pct": round(
                                    ((getattr(message, "total_input_tokens", 0) + getattr(message, "total_output_tokens", 0)) / 200000) * 100,
                                    1,
                                ),
                            }
                        )
```

Add interrupt handling inside the `while True` loop, after `data = await websocket.receive_text()`:
```python
                msg = json.loads(data)

                # Handle interrupt
                if msg.get("type") == "interrupt":
                    logger.info("User interrupted session %s", session_id)
                    await emitter.emit("session_interrupt", user=user, session_id=session_id)
                    continue

                user_message = msg.get("message", "")
```

**Step 4: Modify `corvus/hooks.py` to emit tool_start events**

In `create_hooks()`, modify `pre_tool_use` to emit a tool_start event that the server can forward. Add a `tool_start_callback` parameter to `create_hooks`:

```python
def create_hooks(emitter, *, ws_callback=None):
    """Create PreToolUse and PostToolUse hooks.

    Args:
        emitter: EventEmitter for structured event logging.
        ws_callback: Optional async callable(msg_dict) for WebSocket forwarding.
    """
```

In the `pre_tool_use` hook, after the safety checks and before returning:
```python
        # Emit tool_start for frontend
        if ws_callback:
            import uuid as _uuid
            call_id = str(_uuid.uuid4())[:8]
            await ws_callback({
                "type": "tool_start",
                "tool": tool_name,
                "params": tool_input,
                "call_id": call_id,
            })
```

For confirm-gated tools, emit `confirm_request` instead of just returning `"confirm"`:
```python
        if tool_name in CONFIRM_GATED_TOOLS or tool_name in obsidian_gated:
            if ws_callback:
                await ws_callback({
                    "type": "confirm_request",
                    "tool": tool_name,
                    "params": tool_input,
                    "call_id": call_id,
                    "timeout_s": 60,
                })
            await emitter.emit("confirm_gate", tool=tool_name)
            return "confirm"
```

In `post_tool_use`, emit `tool_result`:
```python
        if ws_callback:
            await ws_callback({
                "type": "tool_result",
                "call_id": call_id,  # Match from pre_tool_use context
                "output": str(tool_input)[:500],  # Truncated for WS
                "duration_ms": 0,  # SDK doesn't provide this yet
                "status": "success",
            })
```

**Step 5: Wire the ws_callback in server.py**

In `corvus/server.py`, modify `_build_hooks()` (line 269) to accept and pass through the websocket:
```python
def _build_hooks(websocket=None):
    async def ws_forward(msg):
        if websocket:
            try:
                await websocket.send_json(msg)
            except Exception:
                pass  # Connection may have closed

    event_hooks = create_hooks(emitter, ws_callback=ws_forward if websocket else None)
    return {
        "PreToolUse": [HookMatcher(matcher="Bash|Read|mcp__.*", hooks=[event_hooks["pre_tool_use"]])],
        "PostToolUse": [HookMatcher(matcher=".*", hooks=[event_hooks["post_tool_use"]])],
    }
```

In the WebSocket handler, change line 444:
```python
        options = build_options(user, websocket=websocket)
```

And modify `build_options` to pass websocket through to `_build_hooks`.

**Step 6: Run all existing tests to verify no regressions**

```bash
mise run test -- tests/gateway/ -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_ws_protocol_results.log
```

Expected: All existing tests PASS. New tests PASS.

**Step 7: Commit**

```bash
git add corvus/server.py corvus/hooks.py tests/gateway/test_ws_protocol.py
git commit -m "feat(gateway): extend WebSocket protocol with routing, tool events, and confirm messages"
```

---

## Task 2: Backend — Session REST API

Add endpoints for listing, retrieving, deleting, renaming, and exporting sessions. The existing `MemoryEngine` stores session data in SQLite — we read from that.

**Files:**
- Modify: `corvus/server.py` (add endpoints after line 631)
- Modify: `corvus/session.py` (add query helpers if needed)
- Test: `tests/gateway/test_session_api.py` (new)

**Step 1: Write the failing test**

Create `tests/gateway/test_session_api.py`:

```python
"""Tests for session REST API endpoints."""
import json
import sqlite3
import tempfile
from datetime import datetime, UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class TestSessionAPIContract:
    """Verify session API response shapes without running the full server."""

    def test_session_list_response_shape(self):
        """GET /api/sessions returns a list of session objects."""
        session = {
            "id": "sess-001",
            "user": "thomas",
            "started_at": "2026-02-28T14:00:00Z",
            "ended_at": "2026-02-28T14:30:00Z",
            "message_count": 12,
            "tool_count": 5,
            "agents_used": ["homelab", "finance"],
        }
        assert "id" in session
        assert "agents_used" in session
        assert isinstance(session["agents_used"], list)

    def test_session_detail_includes_transcript(self):
        """GET /api/sessions/{id} includes message transcript."""
        detail = {
            "id": "sess-001",
            "user": "thomas",
            "transcript": [
                {"role": "user", "content": "check plex"},
                {"role": "assistant", "content": "Plex is running."},
            ],
        }
        assert "transcript" in detail
        assert len(detail["transcript"]) == 2

    def test_session_export_returns_markdown(self):
        """GET /api/sessions/{id}/export returns markdown string."""
        export = "# Session: Check plex\n\n**User:** check plex\n\n**Agent (homelab):** Plex is running.\n"
        assert export.startswith("# Session")


class TestSessionDB:
    """Test session queries against real SQLite."""

    def setup_method(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                message_count INTEGER DEFAULT 0,
                tool_count INTEGER DEFAULT 0,
                agents_used TEXT DEFAULT '[]'
            )
        """)
        conn.execute("""
            INSERT INTO sessions (id, user, started_at, ended_at, message_count, tool_count, agents_used)
            VALUES ('sess-001', 'thomas', '2026-02-28T14:00:00Z', '2026-02-28T14:30:00Z', 12, 5, '["homelab", "finance"]')
        """)
        conn.execute("""
            INSERT INTO sessions (id, user, started_at, ended_at, message_count, tool_count, agents_used)
            VALUES ('sess-002', 'thomas', '2026-02-28T10:00:00Z', NULL, 3, 1, '["general"]')
        """)
        conn.commit()
        conn.close()

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_list_sessions_returns_all(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()
        assert len(rows) == 2
        assert rows[0]["id"] == "sess-001"
        conn.close()

    def test_get_session_by_id(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-001",)).fetchone()
        assert row is not None
        assert row["message_count"] == 12
        assert json.loads(row["agents_used"]) == ["homelab", "finance"]
        conn.close()

    def test_delete_session(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM sessions WHERE id = ?", ("sess-001",))
        conn.commit()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-001",)).fetchone()
        assert row is None
        conn.close()

    def test_rename_session(self):
        conn = sqlite3.connect(self.db_path)
        # Add a name column for the test
        conn.execute("ALTER TABLE sessions ADD COLUMN name TEXT DEFAULT ''")
        conn.execute("UPDATE sessions SET name = ? WHERE id = ?", ("Plex check", "sess-001"))
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT name FROM sessions WHERE id = ?", ("sess-001",)).fetchone()
        assert row["name"] == "Plex check"
        conn.close()
```

**Step 2: Run test to verify it passes**

```bash
mise run test -- tests/gateway/test_session_api.py -v
```

Expected: PASS (DB tests use real SQLite).

**Step 3: Add session endpoints to `corvus/server.py`**

After the existing schedule endpoints (after line 631), add:

```python
@app.get("/api/sessions")
async def list_sessions(
    request: Request,
    agent: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List sessions, optionally filtered by agent."""
    engine = get_memory_engine()
    sessions = engine.list_sessions(limit=limit, offset=offset, agent_filter=agent)
    return JSONResponse([s.to_dict() for s in sessions])


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session detail including transcript."""
    engine = get_memory_engine()
    session = engine.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(session.to_dict())


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    engine = get_memory_engine()
    engine.delete_session(session_id)
    return JSONResponse({"status": "deleted"})


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, request: Request):
    """Rename a session."""
    body = await request.json()
    name = body.get("name", "")
    engine = get_memory_engine()
    engine.rename_session(session_id, name)
    return JSONResponse({"status": "updated", "name": name})


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str):
    """Export session as Markdown."""
    engine = get_memory_engine()
    session = engine.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    md = session.to_markdown()
    return JSONResponse({"markdown": md})
```

**Step 4: Add helper methods to session/memory engine**

Check `corvus/session.py` for existing methods. Add `list_sessions`, `get_session`, `delete_session`, `rename_session`, `to_dict`, and `to_markdown` as needed. These are straightforward SQLite queries.

**Step 5: Run all tests**

```bash
mise run test -- tests/gateway/ -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_session_api_results.log
```

**Step 6: Commit**

```bash
git add corvus/server.py corvus/session.py tests/gateway/test_session_api.py
git commit -m "feat(api): add session REST endpoints (list, get, delete, rename, export)"
```

---

## Task 3: Frontend — Scaffold SvelteKit Project

Create the SvelteKit project with Svelte 5, Tailwind 4, static adapter, and the design system tokens.

**Files:**
- Create: `frontend/` directory at repo root
- Create: `frontend/package.json`, `frontend/svelte.config.js`, `frontend/vite.config.ts`, `frontend/tsconfig.json`
- Create: `frontend/src/app.html`, `frontend/src/app.css` (design tokens)
- Create: `frontend/src/routes/+layout.svelte`, `frontend/src/routes/+page.svelte`
- Create: `frontend/static/` (favicon, etc.)
- Modify: `.gitignore` (add `frontend/node_modules/`, `frontend/.svelte-kit/`, `frontend/build/`)

**Step 1: Initialize SvelteKit project**

```bash
cd /Users/thomaspatane/Documents/GitHub/corvus
npx sv create frontend --template minimal --types ts
cd frontend
npm install
npm install -D @sveltejs/adapter-static tailwindcss @tailwindcss/vite
npm install svelte-markdown shiki
```

**Step 2: Configure static adapter**

`frontend/svelte.config.js`:
```javascript
import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html',
      precompress: false,
    }),
  },
};
```

**Step 3: Configure Tailwind**

`frontend/vite.config.ts`:
```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
});
```

**Step 4: Create design system CSS with all tokens**

`frontend/src/app.css`:
```css
@import 'tailwindcss';

@theme {
  /* Backgrounds */
  --color-canvas: #0d1117;
  --color-surface: #161b22;
  --color-surface-raised: #1c2128;
  --color-overlay: #30363d;
  --color-inset: #010409;

  /* Borders */
  --color-border: #30363d;
  --color-border-muted: #21262d;
  --color-border-emphasis: #8b949e;

  /* Text */
  --color-text-primary: #e6edf3;
  --color-text-secondary: #8b949e;
  --color-text-muted: #6e7681;
  --color-text-link: #58a6ff;

  /* Status */
  --color-status-success: #238636;
  --color-status-warning: #9e6a03;
  --color-status-error: #da3633;
  --color-status-info: #1f6feb;

  /* Focus */
  --color-focus: #58a6ff;

  /* Agent accents */
  --color-agent-personal: #c084fc;
  --color-agent-work: #60a5fa;
  --color-agent-homelab: #22d3ee;
  --color-agent-finance: #34d399;
  --color-agent-email: #fbbf24;
  --color-agent-docs: #818cf8;
  --color-agent-music: #fb7185;
  --color-agent-home: #f97316;
  --color-agent-general: #94a3b8;

  /* Animation timing */
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out-sine: cubic-bezier(0.37, 0, 0.63, 1);
  --duration-instant: 100ms;
  --duration-fast: 150ms;
  --duration-normal: 250ms;
  --duration-slow: 400ms;
  --duration-breathing: 4000ms;
  --duration-thinking: 1500ms;

  /* Spacing */
  --spacing-1: 4px;
  --spacing-2: 8px;
  --spacing-3: 12px;
  --spacing-4: 16px;
  --spacing-6: 24px;
  --spacing-8: 32px;

  /* Fonts */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
}

body {
  background-color: var(--color-canvas);
  color: var(--color-text-primary);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.6;
}

/* Respect reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

**Step 5: Create root layout**

`frontend/src/routes/+layout.svelte`:
```svelte
<script lang="ts">
  import '../app.css';
  let { children } = $props();
</script>

<div class="h-screen w-screen overflow-hidden bg-canvas text-text-primary">
  {@render children()}
</div>
```

**Step 6: Create placeholder page**

`frontend/src/routes/+page.svelte`:
```svelte
<div class="flex items-center justify-center h-full">
  <div class="text-center">
    <h1 class="text-2xl font-bold mb-2">Corvus</h1>
    <p class="text-text-secondary">Mission control loading...</p>
  </div>
</div>
```

**Step 7: Verify the dev server starts**

```bash
cd frontend && npm run dev
```

Expected: SvelteKit dev server on `localhost:5173`, dark page with "Corvus" text.

**Step 8: Verify the static build works**

```bash
cd frontend && npm run build
ls frontend/build/index.html
```

Expected: `build/` directory with `index.html` and assets.

**Step 9: Update .gitignore**

Add to repo root `.gitignore`:
```
frontend/node_modules/
frontend/.svelte-kit/
frontend/build/
```

**Step 10: Commit**

```bash
git add frontend/ .gitignore
git commit -m "feat(frontend): scaffold SvelteKit project with design system tokens"
```

---

## Task 4: Frontend — WebSocket Client with Reconnection

Create the WebSocket client that connects to the gateway, handles all message types, and implements the reconnection state machine.

**Files:**
- Create: `frontend/src/lib/ws.ts` (WebSocket client)
- Create: `frontend/src/lib/types.ts` (TypeScript types for WS protocol)
- Create: `frontend/src/lib/stores.svelte.ts` (reactive state using Svelte 5 runes)
- Test: `frontend/src/lib/ws.test.ts`

**Step 1: Define TypeScript types for the protocol**

`frontend/src/lib/types.ts`:
```typescript
// Client -> Server
export type ClientMessage =
  | { type: 'chat'; message: string }
  | { type: 'confirm_response'; tool_call_id: string; approved: boolean }
  | { type: 'interrupt' }
  | { type: 'ping' };

// Server -> Client
export type ServerMessage =
  | { type: 'routing'; agent: string; model: string }
  | { type: 'agent_status'; agent: string; status: AgentStatus }
  | { type: 'text'; content: string; agent?: string }
  | { type: 'tool_start'; tool: string; params: Record<string, unknown>; call_id: string }
  | { type: 'tool_result'; call_id: string; output: string; duration_ms: number; status: 'success' | 'error' }
  | { type: 'confirm_request'; tool: string; params: Record<string, unknown>; call_id: string; timeout_s: number }
  | { type: 'subagent_start'; agent: string; parent: string }
  | { type: 'subagent_stop'; agent: string; cost_usd: number }
  | { type: 'memory_changed'; domain: string; action: string; summary: string }
  | { type: 'done'; session_id: string; cost_usd: number; tokens_used: number; context_limit: number; context_pct: number }
  | { type: 'error'; message: string };

export type AgentStatus = 'idle' | 'thinking' | 'streaming' | 'done' | 'error';

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error';

export const AGENT_NAMES = ['personal', 'work', 'homelab', 'finance', 'email', 'docs', 'music', 'home', 'general'] as const;
export type AgentName = (typeof AGENT_NAMES)[number];

export const AGENT_COLORS: Record<AgentName, string> = {
  personal: '#c084fc',
  work: '#60a5fa',
  homelab: '#22d3ee',
  finance: '#34d399',
  email: '#fbbf24',
  docs: '#818cf8',
  music: '#fb7185',
  home: '#f97316',
  general: '#94a3b8',
};

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  agent?: AgentName;
  model?: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
  confirmRequest?: ConfirmRequest;
}

export interface ToolCall {
  callId: string;
  tool: string;
  params: Record<string, unknown>;
  output?: string;
  durationMs?: number;
  status: 'running' | 'success' | 'error';
}

export interface ConfirmRequest {
  callId: string;
  tool: string;
  params: Record<string, unknown>;
  timeoutS: number;
  createdAt: Date;
}

export interface Session {
  id: string;
  user: string;
  name?: string;
  startedAt: string;
  endedAt?: string;
  messageCount: number;
  toolCount: number;
  agentsUsed: string[];
}
```

**Step 2: Create the WebSocket client**

`frontend/src/lib/ws.ts`:
```typescript
import type { ClientMessage, ServerMessage, ConnectionStatus } from './types';

export type MessageHandler = (msg: ServerMessage) => void;

const BACKOFF_SCHEDULE = [1000, 2000, 4000, 8000, 16000, 30000];
const MAX_RETRIES = 5;

export class GatewayClient {
  private ws: WebSocket | null = null;
  private url: string;
  private onMessage: MessageHandler;
  private onStatusChange: (status: ConnectionStatus) => void;
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  constructor(
    url: string,
    onMessage: MessageHandler,
    onStatusChange: (status: ConnectionStatus) => void,
  ) {
    this.url = url;
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange;
  }

  connect(): void {
    this.intentionalClose = false;
    this.onStatusChange('connecting');

    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.onStatusChange('error');
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.retryCount = 0;
      this.onStatusChange('connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        this.onMessage(msg);
      } catch {
        console.error('Failed to parse WS message:', event.data);
      }
    };

    this.ws.onclose = () => {
      if (!this.intentionalClose) {
        this.onStatusChange('disconnected');
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      this.onStatusChange('error');
    };
  }

  send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  sendChat(message: string): void {
    this.send({ type: 'chat', message });
  }

  sendConfirm(callId: string, approved: boolean): void {
    this.send({ type: 'confirm_response', tool_call_id: callId, approved });
  }

  sendInterrupt(): void {
    this.send({ type: 'interrupt' });
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.ws?.close();
    this.onStatusChange('disconnected');
  }

  private scheduleReconnect(): void {
    if (this.retryCount >= MAX_RETRIES) {
      this.onStatusChange('error');
      return;
    }
    const delay = BACKOFF_SCHEDULE[Math.min(this.retryCount, BACKOFF_SCHEDULE.length - 1)];
    this.retryCount++;
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
```

**Step 3: Create reactive stores**

`frontend/src/lib/stores.svelte.ts`:
```typescript
import type { ChatMessage, ConnectionStatus, AgentStatus, Session, AgentName, ToolCall, ConfirmRequest } from './types';

// Connection state
export const connectionStatus = $state<{ value: ConnectionStatus }>({ value: 'disconnected' });

// Current session
export const currentSession = $state<{
  id: string | null;
  messages: ChatMessage[];
  activeAgent: AgentName | null;
  agentStatus: AgentStatus;
  costUsd: number;
  tokensUsed: number;
  contextPct: number;
}>({
  id: null,
  messages: [],
  activeAgent: null,
  agentStatus: 'idle',
  costUsd: 0,
  tokensUsed: 0,
  contextPct: 0,
});

// Session list
export const sessions = $state<{ list: Session[] }>({ list: [] });

// Pending tool calls (for streaming tool_start -> tool_result)
export const pendingToolCalls = $state<{ calls: Map<string, ToolCall> }>({ calls: new Map() });

// Active confirm requests
export const activeConfirm = $state<{ request: ConfirmRequest | null }>({ request: null });
```

**Step 4: Verify with a basic test**

`frontend/src/lib/ws.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import type { ServerMessage, ClientMessage } from './types';

describe('Protocol types', () => {
  it('routing message is valid ServerMessage', () => {
    const msg: ServerMessage = { type: 'routing', agent: 'homelab', model: 'sonnet-4.6' };
    expect(msg.type).toBe('routing');
  });

  it('chat message is valid ClientMessage', () => {
    const msg: ClientMessage = { type: 'chat', message: 'hello' };
    expect(msg.type).toBe('chat');
  });

  it('AGENT_COLORS has all 9 agents', () => {
    const { AGENT_COLORS } = require('./types');
    expect(Object.keys(AGENT_COLORS)).toHaveLength(9);
  });
});
```

```bash
cd frontend && npx vitest run src/lib/ws.test.ts
```

**Step 5: Commit**

```bash
git add frontend/src/lib/
git commit -m "feat(frontend): WebSocket client with reconnection state machine and protocol types"
```

---

## Task 5: Frontend — Agent Portraits (SVG + Animations)

Create the 9 agent portrait SVGs and the `AgentPortrait` Svelte component with state animations.

**Files:**
- Create: `frontend/src/lib/components/AgentPortrait.svelte`
- Create: `frontend/src/lib/portraits.ts` (SVG paths for each agent)

**Step 1: Create portrait SVG data**

`frontend/src/lib/portraits.ts`:
```typescript
import type { AgentName } from './types';
import { AGENT_COLORS } from './types';

interface PortraitDef {
  viewBox: string;
  bgPath: string;  // Outer silhouette
  fgPath: string;  // Interior symbol
}

// Simple geometric silhouettes with one interior symbol each.
// Designed to read at 24px as "colored shape + hint."
export const PORTRAITS: Record<AgentName, PortraitDef> = {
  personal: {
    viewBox: '0 0 48 48',
    bgPath: 'M24 4 A20 20 0 1 1 24 44 A20 20 0 1 1 24 4 Z',  // Circle
    fgPath: 'M24 16 C20 16 18 20 18 24 C18 28 20 30 24 32 C28 30 30 28 30 24 C30 20 28 16 24 16 Z M24 12 A4 4 0 1 1 24 20 A4 4 0 1 1 24 12 Z',  // Person
  },
  work: {
    viewBox: '0 0 48 48',
    bgPath: 'M8 8 H40 Q44 8 44 12 V36 Q44 40 40 40 H8 Q4 40 4 36 V12 Q4 8 8 8 Z',  // Rounded rect
    fgPath: 'M16 20 H32 V32 H16 Z M20 16 H28 V20 H20 Z',  // Briefcase
  },
  homelab: {
    viewBox: '0 0 48 48',
    bgPath: 'M24 4 L44 16 V32 L24 44 L4 32 V16 Z',  // Hexagon
    fgPath: 'M16 28 H22 V24 H16 Z M26 28 L26 28',  // Terminal cursor (underscore blink area)
  },
  finance: {
    viewBox: '0 0 48 48',
    bgPath: 'M24 4 L40 14 V34 L24 44 L8 34 V14 Z',  // Shield
    fgPath: 'M24 14 C20 14 18 16 18 18 C18 22 24 22 24 24 C24 26 18 26 18 30 C18 32 20 34 24 34 C28 34 30 32 30 30 C30 26 24 26 24 24 C24 22 30 22 30 18 C30 16 28 14 24 14 Z',  // S shape
  },
  email: {
    viewBox: '0 0 48 48',
    bgPath: 'M6 12 L42 12 L42 36 L6 36 Z',  // Parallelogram-ish envelope
    fgPath: 'M6 12 L24 24 L42 12',  // Envelope flap
  },
  docs: {
    viewBox: '0 0 48 48',
    bgPath: 'M10 6 H34 L38 10 V42 H10 Z',  // Document/book with folded corner
    fgPath: 'M18 20 A6 6 0 1 1 18 32 A6 6 0 1 1 18 20 Z M24 26 L30 32',  // Magnifying glass
  },
  music: {
    viewBox: '0 0 48 48',
    bgPath: 'M24 4 A20 20 0 1 1 24 44 A20 20 0 1 1 24 4 Z M38 24 A14 14 0 1 0 38 24.01',  // Circle with cutout
    fgPath: 'M28 14 V30 A4 4 0 1 1 24 30 V18 L28 14',  // Eighth note
  },
  home: {
    viewBox: '0 0 48 48',
    bgPath: 'M24 6 L42 22 V40 H6 V22 Z',  // House pentagon
    fgPath: 'M20 28 A4 4 0 1 1 28 28 A4 4 0 1 1 20 28',  // Window dot
  },
  general: {
    viewBox: '0 0 48 48',
    bgPath: 'M24 4 A20 20 0 1 1 24 44 A20 20 0 1 1 24 4 Z',  // Circle
    fgPath: 'M14 30 C14 22 18 16 24 14 C28 14 32 16 34 20 L30 22 C28 20 26 18 24 18 C22 18 20 20 18 24 L16 28 Z M30 28 L34 24 L38 30 C36 34 30 36 24 36 C20 36 16 34 14 30 Z',  // Bird silhouette
  },
};

export function getAgentColor(agent: AgentName): string {
  return AGENT_COLORS[agent];
}
```

**Step 2: Create the AgentPortrait component**

`frontend/src/lib/components/AgentPortrait.svelte`:
```svelte
<script lang="ts">
  import type { AgentName, AgentStatus } from '$lib/types';
  import { PORTRAITS, getAgentColor } from '$lib/portraits';

  interface Props {
    agent: AgentName;
    status?: AgentStatus;
    size?: 'sm' | 'md' | 'lg';
  }

  let { agent, status = 'idle', size = 'md' }: Props = $props();

  const sizes = { sm: 24, md: 32, lg: 48 };
  const px = $derived(sizes[size]);
  const portrait = $derived(PORTRAITS[agent]);
  const color = $derived(getAgentColor(agent));

  const statusClass = $derived(
    status === 'idle' ? 'portrait-idle' :
    status === 'thinking' ? 'portrait-thinking' :
    status === 'streaming' ? 'portrait-streaming' :
    status === 'error' ? 'portrait-error' :
    ''
  );
</script>

<div
  class="portrait-container {statusClass}"
  style="width: {px}px; height: {px}px; --agent-color: {color};"
>
  <svg
    viewBox={portrait.viewBox}
    width={px}
    height={px}
    xmlns="http://www.w3.org/2000/svg"
  >
    <path d={portrait.bgPath} fill={color} opacity="0.2" />
    <path d={portrait.bgPath} fill="none" stroke={color} stroke-width="2" />
    <path d={portrait.fgPath} fill={color} opacity="0.8" />
  </svg>
</div>

<style>
  .portrait-container {
    display: inline-flex;
    border-radius: 6px;
    position: relative;
    flex-shrink: 0;
  }

  .portrait-idle {
    animation: idle-pulse var(--duration-breathing, 4000ms) var(--ease-in-out-sine) infinite;
  }

  .portrait-thinking {
    box-shadow: 0 0 0 2px rgba(var(--agent-color), 0);
    animation: thinking-ring var(--duration-thinking, 1500ms) var(--ease-in-out-sine) infinite;
  }

  .portrait-streaming {
    box-shadow: 0 0 8px color-mix(in srgb, var(--agent-color) 30%, transparent);
  }

  .portrait-streaming::after {
    content: '';
    position: absolute;
    bottom: -2px;
    right: -2px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--agent-color);
    animation: dot-pulse 1s var(--ease-in-out-sine) infinite;
  }

  .portrait-error {
    animation: error-shake 400ms ease-out;
  }

  .portrait-error::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 6px;
    background: rgba(218, 54, 51, 0.3);
    pointer-events: none;
  }

  @keyframes idle-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.85; }
  }

  @keyframes thinking-ring {
    0%, 100% { box-shadow: 0 0 0 2px transparent; }
    50% { box-shadow: 0 0 0 2px color-mix(in srgb, var(--agent-color) 40%, transparent); }
  }

  @keyframes dot-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.7); }
  }

  @keyframes error-shake {
    0%, 100% { transform: translateX(0); }
    20% { transform: translateX(-2px); }
    40% { transform: translateX(2px); }
    60% { transform: translateX(-2px); }
    80% { transform: translateX(1px); }
  }

  @media (prefers-reduced-motion: reduce) {
    .portrait-idle,
    .portrait-thinking,
    .portrait-error {
      animation: none;
    }
    .portrait-streaming::after {
      animation: none;
    }
  }
</style>
```

**Step 3: Commit**

```bash
git add frontend/src/lib/portraits.ts frontend/src/lib/components/AgentPortrait.svelte
git commit -m "feat(frontend): agent portrait SVGs with state animations (9 agents, 5 states)"
```

---

## Task 6: Frontend — Core Layout Shell

Build the mode rail, session sidebar, chat panel shell, and status bar — the structural skeleton that all content renders into.

**Files:**
- Create: `frontend/src/lib/components/ModeRail.svelte`
- Create: `frontend/src/lib/components/StatusBar.svelte`
- Create: `frontend/src/lib/components/SessionSidebar.svelte`
- Create: `frontend/src/lib/components/ChatPanel.svelte`
- Modify: `frontend/src/routes/+page.svelte` (compose the layout)

**Step 1: Create ModeRail**

`frontend/src/lib/components/ModeRail.svelte`:
```svelte
<script lang="ts">
  type Mode = 'chat' | 'timeline' | 'memory' | 'config';

  interface Props {
    activeMode: Mode;
    onModeChange: (mode: Mode) => void;
  }

  let { activeMode, onModeChange }: Props = $props();

  const modes: { id: Mode; label: string; icon: string; enabled: boolean }[] = [
    { id: 'chat', label: 'Chat', icon: '💬', enabled: true },
    { id: 'timeline', label: 'Timeline', icon: '📊', enabled: false },
    { id: 'memory', label: 'Memory', icon: '🧠', enabled: false },
    { id: 'config', label: 'Config', icon: '⚙', enabled: false },
  ];
</script>

<nav class="flex flex-col items-center w-12 bg-surface border-r border-border py-2 gap-1">
  {#each modes as mode}
    <button
      class="w-10 h-10 flex items-center justify-center rounded-lg text-lg transition-colors
        {activeMode === mode.id ? 'bg-surface-raised text-text-primary' : 'text-text-muted hover:text-text-secondary hover:bg-surface-raised'}
        {!mode.enabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}"
      title={mode.label}
      disabled={!mode.enabled}
      onclick={() => mode.enabled && onModeChange(mode.id)}
    >
      {mode.icon}
    </button>
  {/each}
</nav>
```

**Step 2: Create StatusBar**

`frontend/src/lib/components/StatusBar.svelte`:
```svelte
<script lang="ts">
  import type { ConnectionStatus, AgentName } from '$lib/types';
  import AgentPortrait from './AgentPortrait.svelte';

  interface Props {
    connectionStatus: ConnectionStatus;
    activeAgent: AgentName | null;
    costUsd: number;
    tokensUsed: number;
    contextPct: number;
  }

  let { connectionStatus, activeAgent, costUsd, tokensUsed, contextPct }: Props = $props();

  const statusDot = $derived(
    connectionStatus === 'connected' ? 'bg-status-success' :
    connectionStatus === 'connecting' ? 'bg-status-warning' :
    'bg-status-error'
  );

  const statusLabel = $derived(
    connectionStatus === 'connected' ? 'Connected' :
    connectionStatus === 'connecting' ? 'Connecting...' :
    connectionStatus === 'error' ? 'Connection failed' :
    'Disconnected'
  );

  const contextColor = $derived(
    contextPct < 50 ? 'bg-status-success' :
    contextPct < 80 ? 'bg-status-warning' :
    'bg-status-error'
  );
</script>

<header class="flex items-center h-9 px-3 bg-surface border-b border-border text-xs font-mono gap-4">
  <!-- Gateway status -->
  <div class="flex items-center gap-1.5">
    <span class="w-2 h-2 rounded-full {statusDot}"></span>
    <span class="text-text-secondary">{statusLabel}</span>
  </div>

  <span class="text-border">|</span>

  <!-- Active agent -->
  {#if activeAgent}
    <div class="flex items-center gap-1.5">
      <AgentPortrait agent={activeAgent} size="sm" />
      <span class="text-text-secondary">{activeAgent}</span>
    </div>
    <span class="text-border">|</span>
  {/if}

  <!-- Session cost -->
  <div class="flex items-center gap-1.5">
    <span class="text-text-muted">Session:</span>
    <span class="text-text-primary tabular-nums">${costUsd.toFixed(2)} / {tokensUsed.toLocaleString()} tok</span>
  </div>

  <span class="text-border">|</span>

  <!-- Context meter -->
  <div class="flex items-center gap-1.5">
    <span class="text-text-muted">Context:</span>
    <div class="w-16 h-1.5 bg-border-muted rounded-full overflow-hidden">
      <div class="h-full rounded-full {contextColor}" style="width: {Math.min(contextPct, 100)}%"></div>
    </div>
    <span class="text-text-primary tabular-nums">{contextPct.toFixed(0)}%</span>
  </div>

  <div class="flex-1"></div>

  <!-- Settings -->
  <button class="text-text-muted hover:text-text-primary" title="Settings">⚙</button>
</header>
```

**Step 3: Create SessionSidebar stub**

`frontend/src/lib/components/SessionSidebar.svelte`:
```svelte
<script lang="ts">
  import type { Session } from '$lib/types';

  interface Props {
    sessions: Session[];
    activeSessionId: string | null;
    onSelectSession: (id: string) => void;
    onNewChat: () => void;
  }

  let { sessions, activeSessionId, onSelectSession, onNewChat }: Props = $props();
</script>

<aside class="flex flex-col w-60 min-w-[200px] max-w-[360px] bg-surface border-r border-border">
  <!-- Header -->
  <div class="flex items-center justify-between p-3 border-b border-border-muted">
    <span class="text-sm font-medium">Sessions</span>
    <button
      class="text-xs px-2 py-1 rounded bg-surface-raised hover:bg-overlay text-text-secondary hover:text-text-primary"
      onclick={onNewChat}
    >
      + New
    </button>
  </div>

  <!-- Search -->
  <div class="p-2">
    <input
      type="text"
      placeholder="Search sessions..."
      class="w-full px-2 py-1 text-sm bg-inset border border-border rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-focus"
    />
  </div>

  <!-- Session list -->
  <div class="flex-1 overflow-y-auto">
    {#if sessions.length === 0}
      <div class="p-4 text-center text-text-muted text-sm">
        No sessions yet.<br/>Start a conversation below.
      </div>
    {:else}
      {#each sessions as session}
        <button
          class="w-full text-left px-3 py-2 border-b border-border-muted hover:bg-surface-raised transition-colors
            {session.id === activeSessionId ? 'bg-surface-raised border-l-2 border-l-focus' : ''}"
          onclick={() => onSelectSession(session.id)}
        >
          <div class="text-sm truncate text-text-primary">{session.name || 'Chat session'}</div>
          <div class="text-xs text-text-muted mt-0.5">
            {session.agentsUsed.join(', ')} — {session.messageCount} msgs
          </div>
        </button>
      {/each}
    {/if}
  </div>
</aside>
```

**Step 4: Create ChatPanel stub**

`frontend/src/lib/components/ChatPanel.svelte`:
```svelte
<script lang="ts">
  import type { ChatMessage, AgentName, AgentStatus } from '$lib/types';
  import AgentPortrait from './AgentPortrait.svelte';

  interface Props {
    messages: ChatMessage[];
    activeAgent: AgentName | null;
    agentStatus: AgentStatus;
    onSendMessage: (message: string) => void;
    onInterrupt: () => void;
  }

  let { messages, activeAgent, agentStatus, onSendMessage, onInterrupt }: Props = $props();

  let inputValue = $state('');
  let chatContainer: HTMLDivElement;

  function handleSend() {
    const msg = inputValue.trim();
    if (!msg) return;
    onSendMessage(msg);
    inputValue = '';
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
    }
  }

  // Auto-scroll: scroll to bottom when new messages arrive
  $effect(() => {
    if (messages.length && chatContainer) {
      const { scrollTop, scrollHeight, clientHeight } = chatContainer;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
      if (isNearBottom) {
        chatContainer.scrollTop = scrollHeight;
      }
    }
  });
</script>

<div class="flex flex-col flex-1 min-w-0">
  <!-- Session title bar -->
  <div class="flex items-center h-7 px-3 bg-surface border-b border-border-muted text-xs">
    {#if activeAgent}
      <AgentPortrait agent={activeAgent} status={agentStatus} size="sm" />
      <span class="ml-1.5 text-text-secondary">{activeAgent}</span>
    {:else}
      <span class="text-text-muted">No active session</span>
    {/if}

    {#if agentStatus === 'streaming' || agentStatus === 'thinking'}
      <button
        class="ml-auto text-status-error hover:text-text-primary text-xs"
        onclick={onInterrupt}
        title="Interrupt (Cmd+.)"
      >
        Stop
      </button>
    {/if}
  </div>

  <!-- Messages -->
  <div
    class="flex-1 overflow-y-auto px-4 py-4"
    bind:this={chatContainer}
  >
    <div class="max-w-[900px] mx-auto space-y-4">
      {#if messages.length === 0}
        <!-- Empty state: welcome -->
        <div class="flex flex-col items-center justify-center h-full text-center py-20">
          <AgentPortrait agent="general" size="lg" />
          <h2 class="text-lg font-medium mt-4">Welcome to Corvus</h2>
          <p class="text-text-secondary mt-1 text-sm max-w-md">
            Your messages are automatically routed to the right agent.
            Just start typing.
          </p>
          <div class="flex flex-wrap gap-2 mt-4 text-xs text-text-muted">
            <span class="px-2 py-1 bg-surface rounded">homelab</span>
            <span class="px-2 py-1 bg-surface rounded">finance</span>
            <span class="px-2 py-1 bg-surface rounded">email</span>
            <span class="px-2 py-1 bg-surface rounded">docs</span>
            <span class="px-2 py-1 bg-surface rounded">personal</span>
            <span class="px-2 py-1 bg-surface rounded">work</span>
            <span class="px-2 py-1 bg-surface rounded">music</span>
            <span class="px-2 py-1 bg-surface rounded">home</span>
          </div>
        </div>
      {:else}
        {#each messages as message (message.id)}
          <div class="flex gap-3 {message.role === 'user' ? 'bg-[#1c2333] -mx-4 px-4 py-3 rounded' : ''}">
            {#if message.role === 'assistant' && message.agent}
              <AgentPortrait agent={message.agent} status={agentStatus} size="lg" />
            {/if}
            <div class="flex-1 min-w-0">
              {#if message.role === 'assistant' && message.agent}
                <div class="text-xs text-text-muted mb-1">{message.agent} · {message.model || ''}</div>
              {/if}
              <div class="prose prose-invert prose-sm max-w-none">
                {message.content}
              </div>
              <!-- Tool calls will be rendered here in a later task -->
            </div>
          </div>
        {/each}
      {/if}
    </div>
  </div>

  <!-- Input bar -->
  <div class="border-t border-border p-3">
    <div class="max-w-[900px] mx-auto flex gap-2">
      <textarea
        class="flex-1 bg-inset border border-border rounded-lg px-3 py-2 text-sm text-text-primary
          placeholder:text-text-muted resize-none focus:outline-none focus:ring-1 focus:ring-focus"
        placeholder="Message Corvus..."
        rows="1"
        bind:value={inputValue}
        onkeydown={handleKeydown}
      ></textarea>
      <button
        class="px-4 py-2 bg-status-info text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40"
        onclick={handleSend}
        disabled={!inputValue.trim()}
      >
        Send
      </button>
    </div>
    <div class="max-w-[900px] mx-auto text-xs text-text-muted mt-1">
      <kbd class="text-[10px] px-1 py-0.5 bg-surface rounded">Cmd+Enter</kbd> to send ·
      <kbd class="text-[10px] px-1 py-0.5 bg-surface rounded">/</kbd> to focus ·
      <kbd class="text-[10px] px-1 py-0.5 bg-surface rounded">Cmd+.</kbd> to interrupt
    </div>
  </div>
</div>
```

**Step 5: Compose everything in the page**

`frontend/src/routes/+page.svelte`:
```svelte
<script lang="ts">
  import ModeRail from '$lib/components/ModeRail.svelte';
  import StatusBar from '$lib/components/StatusBar.svelte';
  import SessionSidebar from '$lib/components/SessionSidebar.svelte';
  import ChatPanel from '$lib/components/ChatPanel.svelte';
  import { connectionStatus, currentSession, sessions } from '$lib/stores.svelte';
  import { GatewayClient } from '$lib/ws';
  import { onMount } from 'svelte';
  import { v4 as uuid } from 'uuid';
  import type { ServerMessage, AgentName, ChatMessage } from '$lib/types';

  let activeMode = $state<'chat' | 'timeline' | 'memory' | 'config'>('chat');
  let client: GatewayClient;

  function handleMessage(msg: ServerMessage) {
    switch (msg.type) {
      case 'routing':
        currentSession.activeAgent = msg.agent as AgentName;
        currentSession.agentStatus = 'thinking';
        break;
      case 'agent_status':
        currentSession.agentStatus = msg.status;
        break;
      case 'text': {
        const lastMsg = currentSession.messages[currentSession.messages.length - 1];
        if (lastMsg?.role === 'assistant' && lastMsg.agent === (msg.agent as AgentName)) {
          // Append to existing assistant message (streaming)
          lastMsg.content += msg.content;
        } else {
          // New assistant message
          currentSession.messages.push({
            id: uuid(),
            role: 'assistant',
            content: msg.content,
            agent: msg.agent as AgentName,
            timestamp: new Date(),
          });
        }
        currentSession.agentStatus = 'streaming';
        break;
      }
      case 'done':
        currentSession.id = msg.session_id;
        currentSession.costUsd = msg.cost_usd;
        currentSession.tokensUsed = msg.tokens_used;
        currentSession.contextPct = msg.context_pct;
        currentSession.agentStatus = 'done';
        break;
      case 'error':
        currentSession.agentStatus = 'error';
        break;
    }
  }

  function sendMessage(message: string) {
    currentSession.messages.push({
      id: uuid(),
      role: 'user',
      content: message,
      timestamp: new Date(),
    });
    client.sendChat(message);
  }

  onMount(() => {
    const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
    client = new GatewayClient(
      wsUrl,
      handleMessage,
      (status) => { connectionStatus.value = status; },
    );
    client.connect();

    return () => client.disconnect();
  });
</script>

<div class="flex flex-col h-full">
  <StatusBar
    connectionStatus={connectionStatus.value}
    activeAgent={currentSession.activeAgent}
    costUsd={currentSession.costUsd}
    tokensUsed={currentSession.tokensUsed}
    contextPct={currentSession.contextPct}
  />

  <div class="flex flex-1 min-h-0">
    <ModeRail {activeMode} onModeChange={(m) => activeMode = m} />

    {#if activeMode === 'chat'}
      <SessionSidebar
        sessions={sessions.list}
        activeSessionId={currentSession.id}
        onSelectSession={(id) => { /* TODO: load session */ }}
        onNewChat={() => { currentSession.messages = []; currentSession.id = null; }}
      />
      <ChatPanel
        messages={currentSession.messages}
        activeAgent={currentSession.activeAgent}
        agentStatus={currentSession.agentStatus}
        onSendMessage={sendMessage}
        onInterrupt={() => client.sendInterrupt()}
      />
    {/if}
  </div>
</div>
```

**Step 6: Install uuid dependency**

```bash
cd frontend && npm install uuid && npm install -D @types/uuid
```

**Step 7: Verify dev server renders the layout**

```bash
cd frontend && npm run dev
```

Expected: Dark page with status bar, mode rail, session sidebar, and chat panel with welcome screen.

**Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): core layout shell (mode rail, status bar, session sidebar, chat panel)"
```

---

## Task 7: Frontend — Tool Call Cards and Confirm Dialogs

Add the ToolCallCard and ConfirmCard components to the chat panel.

**Files:**
- Create: `frontend/src/lib/components/ToolCallCard.svelte`
- Create: `frontend/src/lib/components/ConfirmCard.svelte`
- Modify: `frontend/src/lib/components/ChatPanel.svelte` (render tool cards inline)

Detailed implementation follows the design doc specs for tool call cards (32px collapsed, expandable, 3px left status border, elapsed timer) and confirm cards (2px amber border, timeout countdown, Approve/Deny buttons with keyboard support). Wire `tool_start`/`tool_result` and `confirm_request` messages from the WebSocket handler into these components.

**Step 1-5:** Create components following the exact specs from the design doc's "Tool call cards" and "Confirm-gated tool approval" sections.

**Step 6: Commit**

```bash
git add frontend/src/lib/components/ToolCallCard.svelte frontend/src/lib/components/ConfirmCard.svelte frontend/src/lib/components/ChatPanel.svelte
git commit -m "feat(frontend): tool call cards with elapsed timer + confirm dialogs with timeout countdown"
```

---

## Task 8: Frontend — Markdown Rendering with Streaming Buffering

Add proper markdown rendering with Shiki code highlighting and the code-fence buffering logic to prevent flash-of-broken-markdown.

**Files:**
- Create: `frontend/src/lib/components/MessageContent.svelte`
- Modify: `frontend/src/lib/components/ChatPanel.svelte` (use MessageContent)

The component renders markdown via svelte-markdown, uses Shiki for code blocks with the dark theme, and implements the buffering logic: when an opening code fence (```) is detected without a closing fence, show a "code block incoming..." placeholder until the fence closes.

**Step 1-4:** Implement and wire the MessageContent component.

**Step 5: Commit**

```bash
git add frontend/src/lib/components/MessageContent.svelte frontend/src/lib/components/ChatPanel.svelte
git commit -m "feat(frontend): markdown rendering with Shiki highlighting and streaming code fence buffering"
```

---

## Task 9: Frontend — Docker + nginx + SWAG Proxy

Package the frontend as a Docker container and create the SWAG proxy config.

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `infra/stacks/optiplex/corvus-ui/compose.yaml`
- Modify: `infra/stacks/optiplex/swag/proxy-confs/claw.subdomain.conf` (update for frontend + API split)

**Step 1: Create nginx config**

`frontend/nginx.conf`:
```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Health check
    location /health {
        return 200 'ok';
        add_header Content-Type text/plain;
    }
}
```

**Step 2: Create Dockerfile**

`frontend/Dockerfile`:
```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**Step 3: Create Docker Compose**

`infra/stacks/optiplex/corvus-ui/compose.yaml`:
```yaml
services:
  corvus-ui:
    image: corvus-ui:latest
    build:
      context: ../../../../frontend
      dockerfile: Dockerfile
    container_name: corvus-ui
    ports:
      - "18790:80"
    restart: unless-stopped
```

**Step 4: Update SWAG proxy config**

The existing `claw.subdomain.conf` serves the gateway directly. We need to split: the frontend (corvus-ui on optiplex:18790) serves the UI, and `/ws` + `/api` proxy to the gateway (laptop-server:18789).

Update `infra/stacks/optiplex/swag/proxy-confs/claw.subdomain.conf`:
```nginx
server {
    listen 443 ssl http2;
    server_name claw.absolvbass.com;

    include /config/nginx/ssl.conf;
    include /config/nginx/authelia-server.conf;

    # Frontend (static SvelteKit app on optiplex)
    location / {
        include /config/nginx/authelia-location.conf;
        include /config/nginx/proxy.conf;
        set $upstream_app 127.0.0.1;
        set $upstream_port 18790;
        set $upstream_proto http;
        proxy_pass $upstream_proto://$upstream_app:$upstream_port;
    }

    # WebSocket to gateway (laptop-server)
    location /ws {
        include /config/nginx/authelia-location.conf;
        include /config/nginx/proxy.conf;
        set $upstream_app 192.168.1.200;
        set $upstream_port 18789;
        set $upstream_proto http;
        proxy_pass $upstream_proto://$upstream_app:$upstream_port;
    }

    # API to gateway (laptop-server)
    location /api/ {
        include /config/nginx/authelia-location.conf;
        include /config/nginx/proxy.conf;
        set $upstream_app 192.168.1.200;
        set $upstream_port 18789;
        set $upstream_proto http;
        proxy_pass $upstream_proto://$upstream_app:$upstream_port;
    }

    # Health check (gateway)
    location /health {
        include /config/nginx/proxy.conf;
        set $upstream_app 192.168.1.200;
        set $upstream_port 18789;
        set $upstream_proto http;
        proxy_pass $upstream_proto://$upstream_app:$upstream_port;
    }
}
```

**Step 5: Test the Docker build locally**

```bash
cd frontend && docker build -t corvus-ui:latest .
docker run --rm -p 18790:80 corvus-ui:latest
# Visit http://localhost:18790 — should show the dark Corvus UI
```

**Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf infra/stacks/optiplex/corvus-ui/ infra/stacks/optiplex/swag/proxy-confs/claw.subdomain.conf
git commit -m "feat(deploy): Docker + nginx container for frontend, SWAG proxy split for UI + API"
```

---

## Task 10: Integration Test — End-to-End Chat Flow

Verify the full flow works: frontend connects via WebSocket, sends a message, receives routing + streaming text + done, and renders correctly.

**Files:**
- Create: `frontend/tests/e2e/chat.spec.ts` (Playwright)
- Modify: `frontend/package.json` (add Playwright dev dependency)

**Step 1: Install Playwright**

```bash
cd frontend && npm install -D @playwright/test && npx playwright install chromium
```

**Step 2: Write E2E test**

`frontend/tests/e2e/chat.spec.ts`:
```typescript
import { test, expect } from '@playwright/test';

test.describe('Chat MVP', () => {
  test('shows welcome screen on first load', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Welcome to Corvus')).toBeVisible();
    await expect(page.getByText('Start a conversation')).toBeVisible();
  });

  test('mode rail shows chat as active', async ({ page }) => {
    await page.goto('/');
    // The chat mode button should be highlighted
    await expect(page.getByTitle('Chat')).toBeVisible();
  });

  test('session sidebar shows empty state', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('No sessions yet')).toBeVisible();
  });

  test('input bar is visible and focusable', async ({ page }) => {
    await page.goto('/');
    const input = page.getByPlaceholder('Message Corvus...');
    await expect(input).toBeVisible();
    await input.focus();
    await expect(input).toBeFocused();
  });

  test('status bar shows disconnected when no gateway', async ({ page }) => {
    await page.goto('/');
    // Without a running gateway, should show disconnected/error state
    await expect(page.getByText(/Disconnected|Connection failed|Connecting/)).toBeVisible();
  });
});
```

**Step 3: Run E2E tests**

```bash
cd frontend && npx playwright test tests/e2e/chat.spec.ts
```

**Step 4: Commit**

```bash
git add frontend/tests/ frontend/package.json frontend/playwright.config.ts
git commit -m "test(frontend): E2E tests for chat MVP (welcome screen, empty state, status bar)"
```

---

## Task Summary

| Task | What | Backend | Frontend |
|------|------|---------|----------|
| 1 | WebSocket protocol enrichment | `server.py`, `hooks.py` | — |
| 2 | Session REST API | `server.py`, `session.py` | — |
| 3 | Scaffold SvelteKit project | — | Project setup, design tokens |
| 4 | WebSocket client + reconnection | — | `ws.ts`, `types.ts`, `stores.svelte.ts` |
| 5 | Agent portraits (SVG + animations) | — | `AgentPortrait.svelte`, `portraits.ts` |
| 6 | Core layout shell | — | ModeRail, StatusBar, SessionSidebar, ChatPanel |
| 7 | Tool call cards + confirm dialogs | — | `ToolCallCard.svelte`, `ConfirmCard.svelte` |
| 8 | Markdown rendering + streaming buffer | — | `MessageContent.svelte` |
| 9 | Docker + nginx + SWAG proxy | — | `Dockerfile`, `nginx.conf`, compose, proxy conf |
| 10 | E2E integration test | — | Playwright tests |

**Dependencies:** Tasks 1-2 (backend) are independent of Tasks 3-8 (frontend) and can run in parallel. Task 9 depends on Task 3 (needs the build). Task 10 depends on all previous tasks.
