# Frontend Mission Control Overhaul — Design Document

**Date:** 2026-03-06
**Status:** Approved
**Goal:** Transform the Corvus frontend from prototype scaffolding into a polished mission-control interface that surfaces the full power of the backend system.

---

## Problem Statement

The backend is rich — 10 agents, 23 WS event types, 50+ REST endpoints, full dispatch/run/trace/memory lifecycle. The frontend has 59 Svelte components, 4 themes, custom fonts, atmospheric effects, agent accent colors, and state animations. But the assembled result feels like a prototype:

- Agent selection hidden behind @-mentions and slash commands
- Dispatch mode invisible (buried in collapsed RecipientPicker)
- No right inspector panel (reference designs show session stats, agent card, sub-agent tree, live traces)
- Welcome screen is sparse (agent circles only, no live system data)
- Context % meter exists but isn't prominent
- Model/personality cards nowhere in the chat flow
- Sub-agents invisible (no hierarchy visualization)
- `AGENT_NAMES` hardcoded in types.ts instead of dynamic from backend
- Live security feed component exists but not wired into main view
- Per-message metadata (cost, latency, tokens) not shown

## Reference Aesthetic

Four reference screenshots define the target:

1. **Permissions & Guardrails** (stitch 1) — Dark ops console with trust score cards, live security feed with APPROVE/DENY buttons, domain sidebar
2. **Agent Configuration** (stitch 2) — Identity blueprint, skill matrix tags, model routing cards, service connections with health status, validation rail
3. **Task Dispatch** (stitch 3) — Parallel execution cards with live terminal output, code diffs, elapsed timers, progress bars, interrupt controls
4. **Chat + Mission Details** (screen 2) — Agent sidebar with status dots, chat with agent identity + error cards, right panel with mission details / environment health / recent logs

Common traits: deep dark backgrounds (#0d1117), card-based layouts with subtle borders, monospace metrics, agent accent color highlights, information density, live data feeds.

## Design Principles

1. **Theme-driven everything** — All visuals flow through CSS variables. Zero hardcoded colors/fonts. Changes propagate to all 4 themes automatically.
2. **Dynamic agents** — Remove hardcoded `AGENT_NAMES`. Derive everything from `agentStore.agents` (backend init message). Graceful fallback for unknown agents.
3. **Animated portraits as living indicators** — Agent portraits are the primary status communication mechanism. Each state (idle/thinking/streaming/done/error/awaiting_confirmation) has distinct, expressive animation per theme.
4. **Information density over whitespace** — More data per screen than Claude/ChatGPT. This is a power-user ops console, not a consumer chat.
5. **Discoverability over hidden commands** — Key actions (agent selection, dispatch mode, model choice) must be clickable, not slash-command-only.

---

## Architecture: 3 Implementation Slices

### Slice 1: Layout + Chat Core

**Goal:** Restructure the page layout and chat experience for mission-control density.

#### 1.1 Three-Panel Layout

Add right inspector panel. The main page becomes:

```
+------+------------+----------------------------+------------------+
| Mode | Left       | StatusBar (full width)     | Right            |
| Rail | Panel      |----------------------------| Inspector        |
| 48px | 240-320px  | Content Area               | 260px            |
|      |            | (chat/agents/tasks/etc)    | (collapsible)    |
|      |            |                            |                  |
|      |            |----------------------------| Session stats    |
|      |            | Composer                   | Agent card       |
|      |            |                            | Sub-agent tree   |
|      |            |                            | Related memory   |
|      |            |                            | Live traces      |
+------+------------+----------------------------+------------------+
```

- Inspector auto-collapses below 1440px viewport width
- Toggle with Cmd+Shift+I
- Each mode can provide its own inspector content

#### 1.2 Prominent Agent Picker

Replace hidden @-mention with a visible agent picker strip in the composer area:

- Horizontal row of agent portrait chips above the textarea
- Click to pin as target agent (highlighted border in agent accent color)
- Long-press or right-click for agent profile popover
- "Router" chip as default (auto-route) with visual indicator
- Dynamic from `agentStore.agents` — no hardcoded list

#### 1.3 Dispatch Mode Toggle

Visible toggle buttons in composer, not slash commands:

```
[Router] [Direct] [Parallel]
```

- Router = default, huginn decides
- Direct = send to pinned agent only
- Parallel = send to all selected agents simultaneously
- When Parallel selected, multi-select agent chips appear

#### 1.4 Enhanced Status Bar

Redesign to match reference density:

- Left: connection dot + "Connected" + agent count badge ("10 agents")
- Center: session name (editable) + active agent chip
- Right: cost + tokens + context meter (full color bar with % label)
- Context meter color transitions: green (<50%) -> amber (50-80%) -> red (>80%) -> critical pulse (>95%)

#### 1.5 Welcome Dashboard

Replace sparse agent circles with live system dashboard:

- **System Health Row:** Gateway status, LiteLLM proxy status, active connections, uptime
- **Agent Grid:** Cards (not circles) showing: portrait + name + model + status dot + specialty tags. Click to start chat with agent.
- **Recent Sessions:** Last 5 sessions with agent, preview, timestamp. Click to resume.
- **Quick Actions:** "New Chat", "Dispatch Task", "View Traces", "Memory Search"

#### 1.6 Remove Hardcoded AGENT_NAMES

- Delete `AGENT_NAMES` const from types.ts
- `AgentName` type becomes `string` (validated at runtime against agentStore)
- `isValidAgentName()` checks against live agent list
- `AgentPortrait` handles unknown agents with generic crow silhouette + neutral accent
- Agent accent colors: backend can provide `accent_color` in agent config, frontend falls back to theme default palette rotation for unknown agents

#### 1.7 Context Meter Enhancement

- Below the status bar: full-width thin progress bar (4px) showing context consumption
- Color from theme CSS variable, transitions through green/amber/red
- Tooltip shows: "12,847 / 200,000 tokens (6.4%) — claude-sonnet-4.6"
- Updates in real-time as streaming progresses

### Slice 2: Agent Identity + Animated Portraits

**Goal:** Make agents feel like living entities with personality, not just names.

#### 2.1 Inspector Agent Card

When an agent is active (responding or pinned), the right inspector shows:

- **Portrait** (large, animated based on state)
- **Name + Label** (e.g., "homelab" / "Infrastructure & DevOps")
- **Personality snippet** — first 2-3 lines of the agent's soul prompt
- **Model routing** — primary model, backend, context limit
- **Capabilities** — tool module badges (bash, http, file_read, etc.)
- **Specialty domains** — memory domain, readable domains
- **Live metrics** — runs today, total cost, avg latency

#### 2.2 Animated Portrait System

6 distinct states, each with expressive theme-driven animation:

**idle:**
- Ops-cockpit: gentle ambient glow breathing (4s cycle), subtle scale pulse (1.02x)
- Retro-terminal: slow scanline sweep across portrait, pixel flicker
- Dark-fantasy: mystical particle float around frame, warm ember glow
- Tactical-RTS: steady green status ring, minimal power-save pulse

**thinking:**
- Ops-cockpit: concentric ring ripples radiating outward in agent color (sonar), frame border pulse
- Retro-terminal: rapid scanline, cursor blink overlay, matrix rain inside frame
- Dark-fantasy: swirling energy vortex around portrait, rune glow intensifies
- Tactical-RTS: rotating radar sweep, amber alert ring, acquisition target overlay

**streaming:**
- Ops-cockpit: data-flow dots traveling along frame perimeter, fill arc showing progress
- Retro-terminal: terminal cursor blink, character-by-character text rain
- Dark-fantasy: flowing energy stream from portrait outward, trail particles
- Tactical-RTS: data burst pulses, progress arc filling clockwise, transmission indicator

**done:**
- All themes: brief success flash in agent accent color, checkmark icon overlay (fades after 2s), glow settles to idle

**error:**
- Ops-cockpit: red pulse + subtle shake (400ms), crack overlay on frame
- Retro-terminal: glitch/static effect, red text flash "ERR"
- Dark-fantasy: frame fracture lines, dark energy discharge
- Tactical-RTS: warning strobe, damage indicator, red alert ring

**awaiting_confirmation:**
- All themes: amber pulsing glow at faster rhythm than idle (1s cycle), attention badge overlay, frame border pulses amber

Implementation: CSS keyframes + `animation-timing-function` controlled by theme token (`smooth` vs `steps()`). All animations respect `prefers-reduced-motion: reduce` with static state labels as fallback.

#### 2.3 Per-Message Agent Identity

Each assistant message shows:
- Agent portrait (small, animated) on the left
- Agent chip: `@homelab` in accent color + model badge `sonnet-4.6`
- Expandable metadata row: cost, tokens, latency, context delta
- Tool calls as collapsible cards with status left-border (green/amber/red)

#### 2.4 Agent Profile Popover

Click any agent portrait or name anywhere in the UI to see:
- Full portrait (large, current state animation)
- Name, label, description
- Model + backend + context limit
- Tool count + capability badges
- "Pin Agent" / "Start Chat" / "View Workspace" actions

### Slice 3: Live Operations

**Goal:** Add real-time operational awareness — the "mission control" layer.

#### 3.1 Inspector Live Metrics

Bottom section of right inspector, always visible:

- **Session Stats:** messages, tool calls, cost, tokens, duration
- **Environment Health:** gateway latency (ms), LiteLLM proxy status, Ollama status
- **Context Window:** visual bar + numeric (e.g., "14,231 / 200,000 — 7.1%")

#### 3.2 Sub-Agent Tree

When a dispatch routes to multiple agents:

```
Dispatch #d-001
+-- huginn (router) ......... done 0.2s
+-- finance (run-001) ....... streaming $0.02
+-- homelab (run-002) ....... thinking
    +-- homelab-nfs (sub) ... idle
```

- Tree view in inspector
- Each node shows: portrait (mini) + name + status + elapsed + cost
- Click to focus that agent's output in the chat
- Expand to see tool calls per run

#### 3.3 Live Trace Feed

In inspector or as bottom strip (user preference):

- Real-time security/hook events from `/ws/traces`
- Each row: timestamp + agent dot + event type + summary
- Pending confirms highlighted with APPROVE/DENY buttons
- Filter by agent or event type
- Links to full trace detail

#### 3.4 Task Dispatch Cards

In tasks mode, running tasks as visual cards (matching stitch 3 reference):

- Card per active run with: agent portrait + name + model + elapsed timer
- Live output area (terminal-style monospace, auto-scroll)
- Progress indicator (if available)
- Interrupt button
- Cost accumulator
- Code diff preview (if file modifications detected)

---

## Theme Compatibility Matrix

Every visual element maps to CSS variables:

| Element | CSS Variable(s) | Notes |
|---------|-----------------|-------|
| Inspector background | --color-surface | Same as sidebar |
| Inspector border | --color-border | Left border separator |
| Agent card bg | --color-surface-raised | Elevated surface |
| Context meter | --color-success/warning/error | Transitions by % |
| Portrait glow | --color-agent-{name} | Per-agent accent |
| Portrait frame | theme.portraitFrame.shape | circle/hex/diamond/square |
| Animation easing | --theme-easing | smooth vs stepped |
| Animation duration | --theme-duration-scale | Scale factor per theme |
| Metrics font | --font-mono | Monospace for numbers |
| Atmospheric bg | theme.atmosphere | Scanlines/noise/grid/none |

No new hardcoded values. All slices work across all 4 themes automatically.

---

## What We Keep (No Changes)

- All 59 existing components — refactored composition, not rewrite
- WebSocket protocol and GatewayClient
- API clients (sessions, agents, memory, traces, control)
- Orchestrator state machine
- Theme registry and ThemeProvider
- Store architecture (svelte 5 runes)

## What We Change

- `+page.svelte` layout — add inspector panel column
- `types.ts` — remove hardcoded `AGENT_NAMES`, make dynamic
- `ChatComposer.svelte` — add agent picker strip + dispatch toggle
- `StatusBar.svelte` — enhance density + context meter
- `AgentPortrait.svelte` — richer state animations per theme
- `ChatMessageList.svelte` — per-message agent identity + metadata
- Welcome screen — replace with live dashboard
- New components: `InspectorPanel`, `AgentProfileCard`, `SubAgentTree`, `LiveTraceFeed`, `ContextMeter`, `WelcomeDashboard`, `AgentPickerStrip`, `DispatchModeToggle`

---

## Success Criteria

1. Opening the app shows a live dashboard, not empty circles
2. You can click an agent to start talking to them
3. You can see and switch dispatch mode without typing commands
4. The right inspector shows live session stats, agent card, and trace feed
5. Agent portraits visually animate based on what the agent is doing
6. Context % is always visible and prominent
7. All 4 themes render the new layout correctly with their distinct aesthetics
8. No hardcoded agent names — new agents from backend config appear automatically
9. Sub-agent dispatch tree visible when multi-agent routing occurs
10. Tested with real backend data flowing through WebSocket
