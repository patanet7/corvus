# Corvus Frontend Design

**Date:** 2026-02-28
**Status:** Approved (post-audit revision)
**Approach:** Incremental (Phase 1 → 4), purpose-built SvelteKit frontend

---

## Overview

A self-hosted, mission-control-style web frontend for the Corvus multi-agent gateway. Served as a static SvelteKit app behind SWAG/Authelia, communicating with the Python gateway via WebSocket (chat) and REST API (data).

**Key design decisions:**
- **Session-first navigation** — sessions are the primary unit, not agents. The router decides which agent handles each message. One conversation can span multiple agents.
- **Mode rail + contextual sidebar + chat + collapsible inspector** — four-zone layout with top-level mode switching via vertical icon rail
- **Timeline view** — real-time event stream with multi-criteria filtering, inspired by [claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability)
- **No frontend auth** — Authelia handles authentication at the SWAG layer; the gateway reads `X-Remote-User`

**Influences:**
- OpenClaw Nerve (cockpit density, sub-agent monitoring, memory editor, conflict-safe editing, cron transcripts)
- OpenClaw Studio (clean professionalism, Primer-style design, approvals dashboard)
- PinchChat (session sidebar, tool call cards, WebSocket streaming)
- LobeChat (three-column spatial model, agent-as-first-class-citizen)
- Open WebUI (chat history time grouping, SvelteKit architecture)

---

## Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | SvelteKit 2 + Svelte 5 (runes) | Matches arch v2 spec. Best streaming perf (65% smaller bundles than Next.js). Open WebUI proves it at scale. |
| Styling | TailwindCSS 4 | Utility-first, no component library overhead. Full design control. |
| Markdown | svelte-markdown or mdsvex | Render agent responses with full GFM support. |
| Code highlighting | Shiki | Syntax highlighting in tool output and code blocks. |
| Charts (Phase 3+) | Chart.js or uPlot | Lightweight canvas charts for inline data viz. Not Recharts (bundle size). |
| Build | Vite (via SvelteKit) | Static adapter for production build. |
| Hosting | Docker + nginx | Tiny nginx container serving the static build. Komodo-managed. |
| Component library | None (custom) | Keeps it light, fully owned. Tailwind utility classes. |

---

## Architecture

```
Browser (corvus.absolvbass.com)
  ├── Static SvelteKit app (served by nginx container on optiplex)
  ├── WebSocket → SWAG → laptop-server:18789/ws  (chat)
  └── REST API → SWAG → laptop-server:18789/api/* (data)
```

**Deploy flow:** `git push` → CI builds static output → Docker image → Komodo deploys to optiplex.

**Auth:** Zero frontend auth. Authelia at the SWAG layer provides `X-Remote-User` header. The frontend is transparent to auth.

---

## Design System

### Color Tokens (Dark Theme)

```css
:root {
  /* Backgrounds */
  --bg-canvas: #0d1117;         /* Page background */
  --bg-surface: #161b22;        /* Cards, panels */
  --bg-surface-raised: #1c2128; /* Hover states, active items */
  --bg-overlay: #30363d;        /* Modals, dropdowns */
  --bg-inset: #010409;          /* Inset areas (code blocks) */

  /* Borders */
  --border-default: #30363d;
  --border-muted: #21262d;
  --border-emphasis: #8b949e;

  /* Text */
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --text-muted: #6e7681;
  --text-link: #58a6ff;

  /* Status (desaturated — never confused with agent accents) */
  --status-success: #238636;
  --status-warning: #9e6a03;
  --status-error: #da3633;
  --status-info: #1f6feb;

  /* Functional */
  --focus-ring: #58a6ff;
  --selection: rgba(56, 139, 253, 0.15);
}
```

Light theme inverts backgrounds (`--bg-canvas: #ffffff`, `--bg-surface: #f6f8fa`, etc.) with all agent accents verified for contrast. Toggle in settings gear dropdown.

### Agent Accent Colors

Designed for dark backgrounds. Agent accents are vibrant; status colors are desaturated. Never the same size or shape for both.

| Agent | Accent | Hex | Silhouette | Interior Symbol |
|-------|--------|-----|------------|-----------------|
| personal | Warm violet | `#c084fc` | Circle | Abstract person (curved line) |
| work | Steel blue | `#60a5fa` | Rounded square | Briefcase (rect + handle) |
| homelab | Cyan | `#22d3ee` | Hexagon | Terminal cursor (underscore) |
| finance | Emerald | `#34d399` | Shield | Dollar sign (single stroke) |
| email | Amber | `#fbbf24` | Parallelogram | Envelope flap |
| docs | Indigo | `#818cf8` | Book (rect with spine) | Magnifying glass |
| music | Rose | `#fb7185` | Circle with cutout | Eighth note |
| home | Orange | `#f97316` | House (pentagon) | Dot (window/light) |
| general | Neutral slate | `#94a3b8` | Circle | Corvus bird silhouette |

Note: `home` uses orange (not teal) to avoid hue confusion with `finance` (emerald). The `general` agent portrait uses the Corvus crow — brand identity on the default agent.

### Typography

- **Proportional (chat, UI):** Inter or system font stack. 14px base, 1.6 line-height for chat, 1.4 for UI labels.
- **Monospace (tool output, code):** JetBrains Mono or Fira Code. 13px, 1.5 line-height.
- **Numeric data:** Tabular figures (`font-feature-settings: "tnum"`) for aligned columns in inspector, timeline, costs.

### Spacing Scale (4px base)

| Token | Value | Usage |
|-------|-------|-------|
| `space-1` | 4px | Inline icon gaps, tight element spacing |
| `space-2` | 8px | Within cards, between label and value |
| `space-3` | 12px | Between related elements in a group |
| `space-4` | 16px | Card padding, section gaps |
| `space-6` | 24px | Between card groups, panel padding |
| `space-8` | 32px | Major section dividers |

Ops cockpit density: 16px card padding (not 24), 8px between elements (not 12).

### Animation Timing

```css
:root {
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out-sine: cubic-bezier(0.37, 0, 0.63, 1);
  --duration-instant: 100ms;
  --duration-fast: 150ms;
  --duration-normal: 250ms;
  --duration-slow: 400ms;
  --duration-breathing: 4000ms;
  --duration-thinking: 1500ms;
}
```

All animations respect `prefers-reduced-motion: reduce` — disable all motion, show static state indicators instead.

### Accessibility (non-negotiable even for single-user)

1. All text meets 4.5:1 contrast against dark backgrounds (WCAG AA)
2. Color is never the sole indicator — always paired with icon shape or text label
3. Visible 2px focus rings on all focusable elements (`--focus-ring` color)
4. `prefers-reduced-motion` respected for all portrait and transition animations

---

## Layout — Mission Control

Four-zone layout: mode rail + contextual sidebar + chat + collapsible inspector.

```
┌──────┬──────────────────┬───────────────────────────────┬──────────────────┐
│      │                  │ [portrait] homelab · Sonnet   │                  │
│  💬  │  Sessions        │ ──────────────────────────    │  Inspector       │
│      │  ─────────────   │                               │  ──────────────  │
│  📊  │  🔍 Search...    │  You           14:32          │                  │
│      │                  │  check if plex is running     │  Session         │
│  🧠  │  ● Active        │                               │  ├ tokens: 2,847 │
│      │  ├ ● Chat        │  [portrait] homelab   14:32   │  ├ cost: $0.04   │
│  ⚙   │  │   general     │  I'll check the container.   │  ├ context: 14%  │
│      │  └ ⟳ NAS backup │                               │  ├ latency: 230ms│
│      │     homelab      │  ┌─ ✓ bash ────── 0.8s ──┐   │  └ tools: 3      │
│      │                  │  └────────────────────────┘   │                  │
│      │  Today           │                               │  Agent: homelab  │
│      │  • Budget rev    │  Plex is running, uptime 3d.  │  └ model, tools  │
│      │    finance       │                               │                  │
│      │                  │  ──── [portrait] finance ──── │  Memories (3)    │
│      │  Yesterday       │                               │  └ plex-docker.. │
│      │  • Docker migr   │  You: what did I spend today? │                  │
│      │    homelab       │                               │                  │
│      │                  │  ┌──────────────────────────┐ │                  │
│      │  ⚙ Background    │  │ Message...      Send ▶  │ │                  │
│      │  └ Daily digest  │  └──────────────────────────┘ │                  │
│      │    email ⟳      │                               │                  │
└──────┴──────────────────┴───────────────────────────────┴──────────────────┘
 48px      240px              remaining (max 900px)            260px
           resizable          centered content                 resizable
           min:200 max:360                                     min:200 max:360
```

### Mode Rail (far left, ~48px, always visible)

Vertical icon strip — top-level view switching (like VS Code activity bar):
- 💬 **Chat** (default) — session sidebar + chat panel
- 📊 **Timeline** — filter sidebar + event stream
- 🧠 **Memory** — domain filter sidebar + memory browser
- ⚙ **Config** — nav sidebar + config editor

Active mode highlighted. When switching modes, the contextual sidebar transforms (session list → filter panel → domain list → config nav). Center panel crossfades (150ms, no slide — no spatial implication between views).

### Top Status Bar (36px, always visible)

```
[⬤ Connected] [Agents: 3/9] [Session: $0.12 / 2.8k tokens] [Context: ━━━━░░ 14%] [Latency: 230ms] [⚙]
```

- Gateway connection status (green/yellow/red dot)
- Active agent count out of total
- Current session cost + token count (live-updating)
- **Context window meter** — thin progress bar, green <50%, amber 50-80%, red >80%
- **WebSocket latency** — last round-trip time
- Active agent portrait (24×24) next to agent name
- Settings gear icon + dark/light toggle
- Separator between session-specific and system-wide metrics
- Font: 12px, monospace for numeric values

### Left Panel — Session Navigator (~240px, resizable, collapsible)

- **Search/filter bar** — filter by agent name, status, or text
- **Active sessions** — live status indicators, agent portrait (32×32) per session
  - Each item: 56px height, 8px/12px padding
  - Shows: preview text (14px, single-line ellipsis), agent badge, message count, status dot (6px)
  - Active session: 3px left border in agent accent color + `--bg-surface-raised` background
  - Hover: `--bg-surface-raised`
- **Historical sessions** — grouped by time (Today / Yesterday / Older)
- **Background/cron sessions** — separate collapsible section with running indicators
- **Right-click context menu** on sessions: Rename, Delete, Export as Markdown
- **"New Chat" button** at top

### Center Panel — Chat (remaining width, content max 900px centered)

**Session title bar** (28px, top of chat panel):
- Session name/preview, active agent portrait + name, sidebar collapse toggle
- Visible when sidebar is collapsed so user always has context

**Context window bar** — thin progress bar below title bar, color-coded by fill percentage

**Agent routing divider** — when agent changes mid-conversation:
```
──────── [portrait-24px] homelab / claude-sonnet-4-6 ────────
```
Full-width 1px rule, centered label, agent accent at 5% opacity background stripe (32px tall), 16px margins.
Previous agent's last message gets a subtle "handed off to [agent]" footnote in muted text.

**Messages:**
- User messages: distinct background tint (`#1c2333` vs `#161b22` for agent)
- Agent messages: left-aligned, preceded by agent portrait (48×48) at cluster start
- Max line width: 72ch for agent prose (readability on wide monitors)
- Code blocks: `--bg-inset` background, 1px `--border-default` border, copy button on hover (top-right), language label

**Tool call cards** (inline, collapsible):
```
Collapsed (32px):
┌─ [status-icon] tool-name ─────────────── 0.8s ─ [chevron] ┐
└────────────────────────────────────────────────────────────┘
3px left border in status color. 13px monospace tool name, 12px duration.

Expanded:
┌─ [status-icon] tool-name ─────────────── 0.8s ─ [chevron] ┐
│  Params:                                                    │
│    command: "ssh patanet7@100.116... 'docker ps'"           │
│  Output:                                                    │
│    CONTAINER ID   IMAGE         STATUS                      │
│    a3f8b2c...     plex:latest   Up 3 days                   │
│    [Show all (47 lines)]                                    │
└─────────────────────────────────────────────────────────────┘
12px monospace, max-height: 200px with scroll. Surface background, 1px border.
```

- Consecutive tool calls from same agent turn: grouped into "N tool calls" summary bar (32px collapsed). Last tool call expanded by default.
- Long-running tools: elapsed time counter updating every second (not just final duration)
- Tool output truncation: first 50 lines default, "Show all (N lines)" button
- Nested tool calls (sub-agents): 16px left indent per level, cap at 3 visual levels, "(+N deeper)" counter for deeper nesting

**Confirm-gated tool approval:**
```
┌─ APPROVAL REQUIRED ─────────────────────────────────────────┐
│  [portrait-32px]  email_send                                 │
│                                                              │
│  To:       someone@example.com                               │
│  Subject:  Invoice follow-up                                 │
│  Body:     "Hi, just following up on the outstanding..."     │
│                                                              │
│  [Approve]  [Deny]                      Expires in 47s       │
│                                         ━━━━━━━━━━░░░░       │
└──────────────────────────────────────────────────────────────┘
2px amber border with subtle glow. Background: #1c1c14 (warm-tinted, distinct).
Approve: green bg (#238636), white text. Deny: outlined, red on hover.
Timeout bar: amber, animating from full to empty over 60s.
Keyboard: Enter = Approve, Backspace = Deny (when focused).
Full tool params always visible (truncated params defeat the purpose).
```

**Sub-agent blocks** — nested/indented with smaller portrait (24×24), different border color, showing sub-agent identity.

**Streaming behavior:**
- Token-by-token with cursor indicator
- **Scroll management:** If user is within 100px of bottom, auto-scroll. If scrolled up, show floating "New content below" pill — click to jump. Resume auto-scroll when user scrolls to bottom.
- **Markdown buffering:** When opening code fence detected, hold rendering until closing fence arrives. Show "code block incoming..." placeholder to prevent flash-of-broken-markdown.
- **Expandable input:** Input grows from single-line to multi-line (Shift+Enter or drag handle) for long prompts.

**Scroll navigation:** Floating "scroll to latest" button when >2 viewports from bottom.

### Right Panel — Inspector (~260px, resizable, collapsible)

Collapses via `Cmd+Shift+I` or button. **Auto-collapses below 1440px viewport** (becomes overlay when manually opened).

Accordion-style layout — most relevant section auto-expands:

- **Session stats header** (always visible, compact 2-3 lines): tokens, cost, context %, tool count, duration, latency
- **Active agent** (collapsible drawer): model, tools, Obsidian paths, memory domain. Portrait (48×48) with status label.
- **Sub-agent tree** (collapsible, only visible when sub-agents active): hierarchy view with status per node
- **Related memories** (collapsible): auto-queried via FTS5 from conversation keywords

In Phase 2+, inspector adds tab-switchable views (Session / Traces / Memory).

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Focus chat input |
| `Cmd+Enter` | Send message |
| `Cmd+K` | Command palette |
| `Cmd+.` | Interrupt/cancel current agent execution |
| `Cmd+1-9` | Jump to nth session |
| `Cmd+Shift+I` | Toggle inspector panel |
| `Cmd+Shift+S` | Toggle session sidebar |
| `Cmd+Shift+T` | Reopen last closed session |
| `Cmd+Shift+C` | Copy last agent response to clipboard |
| `Cmd+T` | Open timeline view |
| `j/k` | Navigate session list (when sidebar focused) |
| `Enter` | Open selected session (sidebar focused) |
| `Esc` | Close current overlay/modal/palette |

### Command Palette (`Cmd+K`)

Centered modal, 480px wide, max 8 visible results, 200ms fade-in. Dark surface (`#1c2128`) with `--border-default` border. Search input with autofocus. Arrow keys to navigate, Enter to select, Esc to close. Fuzzy search.

Action types:
- **Jump to session:** Type name or agent, fuzzy-matched
- **Switch view:** "timeline", "memory", "config"
- **Agent actions:** "@homelab" — start new session with specific agent
- **System actions:** "reconnect", "clear session", "toggle inspector", "toggle dark mode"
- **Trigger cron:** "run [schedule-name]"
- **Search memory:** "memory [query]"

### Responsive Breakpoints

| Viewport | Behavior |
|----------|----------|
| >1440px | Full four-zone layout. Inspector visible by default. |
| 1280-1440px | Inspector auto-collapsed. Overlay when opened. |
| 1024-1280px | Session sidebar becomes overlay drawer. Title bar shows session name as clickable element to open drawer. |
| <1024px | Single-panel with bottom nav (Chat/Sessions/Timeline/Config). Slide-over inspector. |

**Ultra-wide (>2560px):** Chat content stays max 900px centered. Remaining space is comfortable negative space.

---

## Agent Portraits — Animated Identity System

Each agent has a distinctive animated portrait (48×48 in chat, 32×32 in sidebar, 24×24 in status bar).

### Visual Style — Simple Geometric Silhouettes

At 24px, detail collapses — portraits function as "colored shape + hint." Each portrait has:
1. Unique **outer silhouette** (circle, hexagon, shield, house, etc.)
2. Single **interior symbol** (1-2 strokes max)
3. Agent accent color as dominant fill
4. Dark interior or subtle gradient for depth

See the Agent Accent Colors table above for specific silhouettes and symbols per agent.

### State Animations (CSS keyframes, no JS)

| State | Effect | Implementation | Duration |
|-------|--------|----------------|----------|
| `IDLE` | Opacity pulse | `opacity: 1.0 → 0.85 → 1.0` | 4s loop, `--ease-in-out-sine` |
| `THINKING` | Glow ring pulse | `box-shadow: 0 0 0 2px rgba(accent, 0) → rgba(accent, 0.4)` | 1.5s loop |
| `STREAMING` | Steady glow + pulsing dot | `box-shadow: 0 0 8px rgba(accent, 0.3)` constant, adjacent 6px dot pulses | Constant + 1s dot pulse |
| `DONE` | Brightness flash | `filter: brightness(1.3) → 1.0` | 0.3s once |
| `ERROR` | Shake + red overlay | Container `translateX(±2px)`, semi-transparent red overlay preserving agent color | 0.4s once → idle |

Key implementation notes:
- Use `will-change: transform, opacity` only during active animation — remove when idle
- Shake applies to container, not SVG (preserves crisp rendering)
- Error red tint is an overlay, not a filter change (agent identity remains visible)
- All animations disabled when `prefers-reduced-motion: reduce` — show static state label instead

### Component API

```svelte
<AgentPortrait agent="homelab" state="streaming" size="md" />
<!-- size: sm (24px), md (32px), lg (48px) -->
```

Portraits shipped as static SVGs in the frontend bundle.

---

## Timeline View (Phase 2)

Replaces the center panel when Timeline mode is active in the mode rail. The contextual sidebar transforms into a filter panel.

```
┌─ Timeline ────────────────────────────────────────────────────────────────┐
│  Filter: [All agents ▾] [All events ▾] [All sessions ▾]  [1m 3m 5m 15m] │
│  [Search event payload...] [P50: 230ms  P95: 1.2s] [Errors: 2 (0.3%)]   │
├───────────────────────────────────────────────────────────────────────────┤
│  Per-agent sparklines (16px tall each, stacked):                         │
│  homelab  ▁▃▅▇▅▃▁▃▅▇                                                    │
│  finance  ▁▁▁▃▅▁▁▁                                                      │
│  email    ▁▁▁▁▁▁▃▅▇                                                     │
├───────────────────────────────────────────────────────────────────────────┤
│  14:32:08  🔧 PreToolUse    bash         homelab  session-a3f...         │
│  14:32:09  ✅ PostToolUse   bash         homelab  session-a3f...  0.8s  │
│  ─── (linked pair: bash call 0.8s) ───                                   │
│  14:32:10  🧭 Routing       finance      —        session-a3f...         │
│  14:32:11  🔧 PreToolUse    firefly_txn  finance  session-a3f...         │
│  14:32:12  🔔 Confirm       email_send   email    session-b7e...         │
│  14:32:15  🧠 MemoryWrite   homelab      —        session-a3f...         │
└───────────────────────────────────────────────────────────────────────────┘
```

**Improvements over initial design:**

- **Per-agent sparklines** instead of single pulse chart — thin horizontal lines (16px each) per active agent, stacked vertically. Shows per-agent activity without ambiguity.
- **Aggregate stats** in filter bar — P50/P95 tool latency, error count + rate
- **Event payload search** — text search across event payloads ("show all bash commands with `docker`")
- **Event linking** — PreToolUse/PostToolUse for same call visually connected with duration span
- **Group by session toggle** — Chronological (default) vs grouped-by-session view
- **Click-through** — clicking session ID navigates to chat view for that session
- **Auto-scroll** with sticky-scroll toggle (live tail vs. historical review)

**Data source:** Gateway `EventEmitter` JSONL events. Backend `GET /api/traces` for historical, WebSocket for live.

---

## WebSocket Protocol (extended)

### Client → Server
```json
{"type": "chat", "message": "check if plex is running"}
{"type": "confirm_response", "tool_call_id": "...", "approved": true}
{"type": "interrupt"}
{"type": "ping"}
```

### Server → Client
```json
{"type": "routing", "agent": "homelab", "model": "sonnet-4.6"}
{"type": "agent_status", "agent": "homelab", "status": "thinking|streaming|done|error"}
{"type": "text", "content": "I'll check the container...", "agent": "homelab"}
{"type": "tool_start", "tool": "bash", "params": {"command": "ssh ..."}, "call_id": "abc"}
{"type": "tool_result", "call_id": "abc", "output": "plex: Up (3 days)", "duration_ms": 800, "status": "success"}
{"type": "confirm_request", "tool": "email_send", "params": {...}, "call_id": "def", "timeout_s": 60}
{"type": "subagent_start", "agent": "homelab-nfs", "parent": "homelab"}
{"type": "subagent_stop", "agent": "homelab-nfs", "cost_usd": 0.01}
{"type": "memory_changed", "domain": "homelab", "action": "save", "summary": "plex running on miniserver"}
{"type": "done", "session_id": "...", "cost_usd": 0.04, "tokens_used": 2847, "context_limit": 200000, "context_pct": 1.4}
{"type": "error", "message": "..."}
```

---

## REST API Endpoints (added incrementally)

### Phase 1
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/sessions` | List sessions (filterable by agent, status, date range) |
| `GET` | `/api/sessions/{id}` | Session detail + transcript |
| `DELETE` | `/api/sessions/{id}` | Delete session |
| `PATCH` | `/api/sessions/{id}` | Rename session |
| `GET` | `/api/sessions/{id}/export` | Export session as Markdown |

### Phase 2
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/traces` | Event log (filterable by agent, event type, session, time range, payload text) |
| `GET` | `/api/traces/{session_id}` | Events for a specific session |
| `GET` | `/api/traces/stats` | Aggregate stats (P50/P95 latency, error rate) |

### Phase 3
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/memory/search` | Memory search (query, domain filter, limit) |
| `GET` | `/api/memory/{id}` | Single memory record with metadata |

### Phase 4
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/config/agents` | List agent definitions |
| `PATCH` | `/api/config/agents/{name}` | Update agent config |
| `GET` | `/api/config/models` | Model routing config |
| `GET` | `/api/config/tools` | Tool registry (which tools each agent has) |
| `GET` | `/api/schedules` | List schedules (already exists) |
| `PATCH` | `/api/schedules/{name}` | Update schedule (already exists) |
| `GET` | `/api/cost` | Cost dashboard (today, week, month, per-agent, per-model) |

---

## UI States

### Empty States
| Surface | Empty State |
|---------|-------------|
| First launch (zero sessions) | Welcome screen: Corvus bird portrait, "Start a conversation" prompt, brief orientation (9 agents, what they do, shortcuts) |
| Session filter no results | "No sessions match [filter]" + clear-filter button |
| Timeline (no events) | "No events yet. Start a conversation to see activity here." |
| Memory (no records) | "No memories stored. Memories are extracted automatically from conversations." |
| Inspector (no session selected) | System health summary: gateway uptime, connected agents, total sessions today |

### Loading States
- **Session list:** 3-4 gray shimmer skeleton bars at 56px each
- **Chat history load:** Full-panel skeleton with message-shaped placeholders
- **Timeline initial:** Flat gray sparkline area + skeleton event rows
- **Inspector sections:** Individual section skeletons (load independently)

### Error States
- **API failure:** Inline error in relevant section + retry button (not full-page error)
- **Agent error during chat:** ERROR portrait animation + red-tinted message card with error text (no stack traces — those go to logs)

### WebSocket Reconnection State Machine

1. **Connection drops:** Amber banner at top of chat: "Connection lost. Reconnecting..." Manual "Retry now" button. Gateway dot → yellow. Existing chat content preserved.
2. **Exponential backoff:** 1s → 2s → 4s → 8s → 16s → 30s (cap)
3. **After 5 failures:** Banner turns red: "Unable to connect to gateway. Check the server is running." Manual "Connect" button.
4. **Successful reconnect:** Banner flashes green "Reconnected" for 2s, disappears. Query `GET /api/sessions/{id}` to catch up on missed messages. Gateway dot → green.

### Notification System

Notification bell icon in status bar with unread count. Dropdown shows recent events:
- Background cron job completed
- Agent errors
- Memory writes
- Confirm requests pending in other sessions

Multi-session awareness: pulsing dot / badge count on sidebar items with new background activity.

---

## Phased Delivery

### Phase 1 — Chat MVP
**Frontend deliverables:**
- SvelteKit project scaffolded (Svelte 5, Tailwind 4, static adapter)
- Mode rail (Chat mode only — others disabled/grayed)
- Session sidebar (240px, resizable) with search/filter, time-grouped history, session context menu (rename, delete, export)
- Session title bar in chat panel
- Chat panel (max 900px centered) with streaming markdown, agent portraits + routing dividers
- Tool call cards (collapsed 32px, expandable, grouped consecutive calls, elapsed timer for long-running)
- Confirm-gated tool approval (inline card with timeout bar)
- Agent portraits (9 SVGs with state animations)
- WebSocket connection with reconnect state machine
- Scroll management (auto-scroll + "New content below" pill)
- Markdown buffering (code fence hold)
- Expandable input bar
- Empty states (first launch, no sessions)
- Loading skeletons
- Error states + reconnection UX
- Dark theme (light theme toggle in settings)
- Docker + nginx container
- SWAG proxy config (`corvus.subdomain.conf`)
- Deploy to `corvus.absolvbass.com`

**Backend changes:**
- Extend WebSocket protocol: `routing`, `agent_status`, `tool_start`, `tool_result`, `confirm_request`, `interrupt`, `memory_changed` messages
- Add `GET/DELETE/PATCH /api/sessions` endpoints
- Add `GET /api/sessions/{id}/export` endpoint

### Phase 2 — Observability
**Frontend deliverables:**
- Top status bar (gateway health, agents, cost, context %, latency)
- Inspector panel (accordion layout, auto-collapse <1440px)
- Timeline mode (per-agent sparklines, filtered event stream, event linking, payload search, aggregate stats)
- Command palette (`Cmd+K`)
- Full keyboard shortcuts
- Notification bell + dropdown
- Responsive breakpoints

**Backend changes:**
- Add `GET /api/traces` + `/api/traces/stats` endpoints
- Add live event forwarding over WebSocket

### Phase 3 — Memory + Structured Output
**Frontend deliverables:**
- Memory mode (search, domain filter, record detail, audit trail)
- Related memories in inspector (auto-queried from conversation context)
- Live memory update via `memory_changed` events
- Structured markers: `[chart:{...}]` and `[table:{...}]` with bracket-balanced parser, inline Chart.js/uPlot rendering

**Backend changes:**
- Add `GET /api/memory/search` and `GET /api/memory/{id}` endpoints
- `MemoryHub.save()` emits `memory_changed` event

### Phase 4 — Config + Cost
**Frontend deliverables:**
- Config mode (agent definitions, model routing, schedules, tool registry)
- Cost dashboard (aggregate by day/week/month, per-agent, per-model)
- Session export as Markdown

**Backend changes:**
- Add config CRUD endpoints
- Add `GET /api/cost` endpoint
- Per-execution cron transcripts

---

## Nerve-Informed Backend Enhancements

Features informed by [OpenClaw Nerve](https://github.com/daggerhashimoto/openclaw-nerve):

### Per-Execution Cron Transcripts
`CronScheduler.execute()` creates a `SessionTranscript`, persists on completion, links via `schedule_name + run_id`. Full audit trail for background jobs.

### Agent Status Lifecycle Events
Add `{"type": "agent_status", "agent": "homelab", "status": "thinking|streaming|done|error"}` WebSocket events. Driven by hooks: `PreToolUse` → thinking, first `TextBlock` → streaming, `ResultMessage` → done.

### Context Window Metrics
Extend `done` message: `{"tokens_used": 2847, "context_limit": 200000, "context_pct": 1.4}`.

### Memory Change Events
`MemoryHub.save()` emits `memory_changed` via `EventEmitter`. Frontend subscribes for live inspector updates.

### Structured Agent Markers (Phase 3+)
Agent system prompts include marker syntax. Frontend bracket-balanced parser renders:
- `[chart:{type:"bar", labels:[...], values:[...]}]` — inline Chart.js visualization
- `[table:{headers:[...], rows:[...]}]` — styled HTML table with dark theme

Deferred to Phase 3 — parser complexity not justified before core chat UX is polished.

---

## Influences & References

| Project | What we take | What we skip |
|---------|-------------|-------------|
| [OpenClaw Nerve](https://github.com/daggerhashimoto/openclaw-nerve) | Cockpit density, sub-agent monitoring, memory editor, conflict-safe editing, cron transcripts, command palette, keyboard-first, agent status lifecycle | Voice I/O, TradingView charts, code editor, device identity pairing |
| [OpenClaw Studio](https://github.com/grp06/openclaw-studio) | Clean professionalism, Primer-style design, approvals dashboard | React/Primer stack |
| [PinchChat](https://github.com/MarlBurroW/pinchchat) | Session sidebar, tool call card design, context usage bars, WebSocket streaming | React stack |
| [LobeChat](https://github.com/lobehub/lobe-chat) | Three-column spatial model, agent accent colors | Next.js + antd stack, agent marketplace |
| [Open WebUI](https://github.com/open-webui/open-webui) | SvelteKit architecture, chat history time grouping, dark/light themes | OpenAI API assumption, multi-user RBAC |
| [claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability) | Timeline view, live pulse chart, multi-criteria filtering, dual-color event rows, auto-scroll toggle | Vue stack, Bun backend |

---

## Non-Goals (explicitly out of scope)

- **Multi-user auth** — Authelia handles this. The frontend is single-user behind SSO.
- **Mobile-first design** — Desktop-first. Responsive degrades gracefully.
- **Agent creation UI** — Phase 4 at earliest. Agents are code/YAML-defined for now.
- **Voice I/O** — Not in initial phases. Revisit after Phase 4.
- **Plugin marketplace** — Corvus doesn't have a plugin system yet.
- **Offline/PWA** — Not needed for a self-hosted system on local network.
- **Workspace file browser / code editor** — Obsidian already covers vault editing.
- **TradingView live charts** — Overkill unless finance agent does market analysis.
