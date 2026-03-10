---
title: "Corvus Frontend Phase 2: Visual Overhaul + Portrait System + Theme Engine"
type: spec
status: partially-implemented
date: 2026-03-01
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Corvus Frontend Phase 2 — Visual Overhaul + Portrait System + Theme Engine

**Date:** 2026-03-01
**Status:** Draft
**Depends on:** Phase 1 Chat MVP (complete, 15 commits on `feature/frontend-phase1`)
**Reference:** `frontend/FUNDAMENTALS.md` — ground truth for all design decisions

---

## Overview

Phase 2 transforms the Corvus frontend from a functional GitHub-dark chat clone into a distinctive, themeable mission control with animated agent portraits. Three workstreams:

1. **Theme Engine** — the skeleton everything hangs on
2. **Universal Portrait System** — format-agnostic, per-agent, state-animated
3. **Visual Overhaul + Audit Fixes** — apply the default theme, fix all Phase 1 bugs
4. **Task Dispatch UX** — send agents off on tasks, monitor in parallel

**Approach:** Theme-first architecture (Approach A from brainstorming). Build the theme system as the foundation, then portraits and visual overhaul layer on top. Bug fixes are independent and can run in parallel.

---

## 1. Theme Engine

### Architecture

```
frontend/src/lib/themes/
  types.ts              — ThemeConfig interface
  registry.ts           — register/get/list themes
  provider.svelte       — <ThemeProvider> root component
  themes/
    ops-cockpit.ts      — default: clean, data-dense, IBM Plex
    retro-terminal.ts   — CRT scanlines, phosphor glow, VT323
    dark-fantasy.ts     — textured surfaces, warm gold, Cinzel
```

### ThemeConfig Interface

```typescript
interface ThemeConfig {
  id: string;
  name: string;

  colors: {
    canvas: string;
    surface: string;
    surfaceRaised: string;
    overlay: string;
    inset: string;
    border: string;
    borderMuted: string;
    borderEmphasis: string;
    textPrimary: string;
    textSecondary: string;
    textMuted: string;
    textLink: string;
    success: string;
    warning: string;
    error: string;
    info: string;
    focus: string;
    agents: Record<AgentName, string>;
  };

  fonts: {
    sans: FontDef;
    mono: FontDef;
    display?: FontDef;   // optional — falls back to sans
  };

  atmosphere: {
    backgroundEffect?: string;    // CSS for body::before (scanlines, grid, texture)
    surfaceTexture?: string;      // CSS background-image for surface elements
    borderStyle?: string;         // 'solid' | 'ridge' | 'double' | custom
    glowColor?: string;           // accent glow for focus/active states
    noiseOpacity?: number;        // grain overlay (0 = none, 0.05 = subtle)
  };

  animations: {
    easing: string;
    durationScale: number;        // 1.0 = normal, 0.5 = snappy, 1.5 = languid
    portraitStyle: 'smooth' | 'stepped';
  };

  portraitFrame: {
    shape: 'circle' | 'square' | 'hexagon' | 'diamond' | 'none';
    border: string;
    background: string;
    glow?: string;
  };

  components: {
    statusBar: {
      background: string;
      separator: string;          // '|' vs '·' vs '—' vs SVG
      fontFamily: 'mono' | 'sans';
    };
    modeRail: {
      iconWeight: number;
      activeIndicator: 'bar' | 'glow' | 'fill' | 'underline';
    };
    chatPanel: {
      userMessageBg: string;
      assistantMessageBg: string;
      maxWidth: string;
      messagePadding: string;
    };
    toolCard: {
      statusBorderWidth: string;
      expandAnimation: 'slide' | 'fade' | 'instant';
    };
    confirmCard: {
      urgencyStyle: 'border' | 'glow' | 'pulse-bg';
      countdownStyle: 'bar' | 'ring' | 'text';
    };
    codeBlock: {
      shikiTheme: string;        // 'github-dark' | 'vitesse-dark' etc
      headerStyle: 'tab' | 'bar' | 'minimal' | 'none';
    };
    sidebar: {
      resizeHandle: 'native' | 'custom-bar' | 'hover-edge';
      activeSessionIndicator: 'left-border' | 'background' | 'glow';
    };
  };

  details: {
    borderRadius: string;         // '4px' | '8px' | '0'
    scrollbarWidth: 'thin' | 'auto' | 'none';
    selectionBg: string;
    selectionText: string;
    kbdStyle: 'beveled' | 'flat' | 'outline';
  };
}

interface FontDef {
  family: string;
  weights: number[];
  source:
    | { type: 'google'; family: string }
    | { type: 'local'; files: Record<number, string> }
    | { type: 'system' };
  fallback: string;
}
```

### ThemeProvider Behavior

1. On mount, reads `localStorage.getItem('corvus-theme')` or defaults to `ops-cockpit`
2. Resolves theme from registry
3. Injects all `colors.*` as `--color-*` CSS custom properties on `:root`
4. Injects `--font-sans`, `--font-mono`, `--font-display` from font definitions
5. Creates `@font-face` rules dynamically for fonts that need loading
6. Injects `--radius-default`, `--scrollbar-width`, etc. from `details`
7. Applies `atmosphere.backgroundEffect` as `body::before` pseudo-element
8. Exposes `setTheme(id)` function via Svelte context for theme switching

### Three Default Themes

| Property | Ops Cockpit (default) | Retro Terminal | Dark Fantasy |
|----------|----------------------|----------------|--------------|
| Font sans | IBM Plex Sans | Share Tech Mono | EB Garamond |
| Font mono | IBM Plex Mono | VT323 | Fira Code |
| Font display | IBM Plex Sans | Press Start 2P | Cinzel Decorative |
| Surface | Flat dark (#161b22) | Pure black (#000) | Textured dark (#1a1510) |
| Border | 1px solid, muted | 1px solid phosphor green | 2px ridge warm gold |
| Border radius | 4px | 0px | 2px |
| Code theme | github-dark | Custom phosphor green | catppuccin-mocha |
| Portrait frame | Circle, subtle border | Square, CRT scanline overlay | Hexagon, ornate gold border |
| Active indicator | Left bar | Glow | Fill |
| Noise | None | CRT scanlines + flicker | Parchment grain |
| Scrollbar | Thin, dark | Green on black | Ornate warm |
| kbd style | Flat | Outline monospace | Beveled stone |
| Confirm style | Border (amber) | Pulse background | Glow |

### Tailwind Integration

The `@theme` block in `app.css` references CSS variables instead of hardcoded values:

```css
@theme {
  --font-sans: var(--theme-font-sans);
  --font-mono: var(--theme-font-mono);
  --color-canvas: var(--theme-color-canvas);
  --color-surface: var(--theme-color-surface);
  /* ... all other tokens ... */
}
```

This means Tailwind classes like `bg-canvas`, `font-mono`, `text-text-primary` automatically use whatever the active theme provides.

---

## 2. Universal Portrait System

### Architecture

```
frontend/src/lib/portraits/
  types.ts              — PortraitConfig, AssetDef interfaces
  registry.ts           — register/get/list per agent
  defaults.ts           — built-in geometric SVG portraits (cleaned up from Phase 1)
  AgentPortrait.svelte  — universal renderer/dispatcher
  renderers/
    SpriteRenderer.svelte    — CSS background-position animation
    SvgRenderer.svelte       — inline SVG with CSS state animations
    ImageRenderer.svelte     — static <img>
    AnimatedRenderer.svelte  — <img> for GIF/APNG/WebP
    LottieRenderer.svelte    — lottie-web player (lazy-loaded)

frontend/static/portraits/
  general/              — Corvus crow assets
    idle.png            — or idle-sprite.png (sprite sheet)
    thinking.png
    ...
  homelab/
  finance/
  ...
```

### PortraitConfig

```typescript
interface PortraitConfig {
  agent: AgentName;
  format: 'sprite' | 'svg' | 'image' | 'animated' | 'lottie';
  states: {
    idle: AssetDef;
    thinking?: AssetDef;
    streaming?: AssetDef;
    done?: AssetDef;
    error?: AssetDef;
  };
  accentColor?: string;  // override theme's agent color
}

type AssetDef =
  | { type: 'sprite'; src: string; frameWidth: number; frameHeight: number; frameCount: number; fps: number }
  | { type: 'svg'; content: string }
  | { type: 'image'; src: string }
  | { type: 'animated'; src: string }
  | { type: 'lottie'; data: object }
```

### Renderer Dispatch

`AgentPortrait.svelte` reads the agent's config from the portrait registry, resolves the current state's asset (falling back to idle, then to accent-color initial), and renders the appropriate sub-renderer inside the theme's portrait frame.

```
┌─────────────────────────┐
│  Theme: portrait frame  │  ← shape, border, glow, background from theme
│  ┌───────────────────┐  │
│  │  Agent: portrait   │  │  ← sprite/SVG/image/GIF/Lottie from agent config
│  │  asset content     │  │
│  └───────────────────┘  │
└─────────────────────────┘
```

### SpriteRenderer

CSS `background-position` animation using `steps()` timing:

```css
.sprite {
  width: var(--frame-width);
  height: var(--frame-height);
  background: url(var(--sprite-src)) no-repeat;
  animation: sprite-play calc(var(--frame-count) / var(--fps) * 1s) steps(var(--frame-count)) infinite;
}
@keyframes sprite-play {
  to { background-position: calc(var(--frame-width) * var(--frame-count) * -1) 0; }
}
```

### Fallback Chain

1. Agent has custom portrait config for current state → use it
2. Agent has custom portrait config but not for this state → use idle
3. Agent has no custom portrait config → use built-in geometric SVG default
4. Nothing available → accent color circle with first letter of agent name

### Asset Management

Portraits live in `frontend/static/portraits/{agent}/`. To add a custom portrait:
1. Drop assets into the agent's directory
2. Add/update the agent's `PortraitConfig` in the portrait registry
3. Done — the renderer handles the rest

---

## 3. Visual Overhaul + Audit Bug Fixes

### Bug Fixes (from Phase 1 audit)

| # | Fix | Details |
|---|-----|---------|
| 1 | **Add DOMPurify** | Sanitize all `{@html}` in MessageContent before rendering |
| 2 | **Focus trap on ConfirmCard** | Trap Tab within the modal, auto-focus Approve button on mount |
| 3 | **Fix double Cmd+. interrupt** | Remove the textarea-level handler, keep only svelte:window |
| 4 | **Fix empty-state centering** | Replace `h-full` with proper flex centering in the messages container |
| 5 | **Fix email portrait** | Open polyline fgPath renders as invisible triangle — fix the path |
| 6 | **Fix homelab portrait** | Degenerate zero-length subpath — remove or replace |
| 7 | **Fix $derived anti-pattern** | Change all `$derived(() => ...)` to plain `$derived(expr)` across 3 components |
| 8 | **Remove agent color duplication** | Delete `AGENT_COLORS` from types.ts, source from theme only |
| 9 | **Extract shared Icon component** | Gear icon (and others) duplicated in ModeRail + StatusBar — extract |
| 10 | **Fix status bar separator visibility** | Use `text-text-muted` instead of `text-border` |
| 11 | **Remove dead buttons** | Settings gear with no handler, "Full output" stubs in ToolCallCard |
| 12 | **Add aria-live to streaming content** | `aria-live="polite"` on active streaming message |
| 13 | **Add aria-label to chat input** | Explicit label, not just placeholder |
| 14 | **Queue messages during reconnection** | Buffer sends while WS is connecting, deliver on open |
| 15 | **Handle all server message types** | Wire subagent_start, subagent_stop, memory_changed, ping→pong |

### Visual Overhaul

All visual changes flow through the theme system:

- **Welcome screen redesign:** Corvus crow portrait (large, animated idle state), distinctive heading in `--font-display`, agent cards with portraits instead of plain text pills
- **Font loading:** ThemeProvider loads actual fonts (IBM Plex for ops cockpit) — no more silent system fallback
- **Atmospheric depth:** Subtle grid/noise overlay via theme's `atmosphere.backgroundEffect`
- **Status bar upgrade:** Proper separators, remove dead settings button, theme-aware font choice
- **Error UI:** Inline error banners in chat (red-tinted card with error text), toast notifications for connection issues
- **Code blocks:** Theme-aware Shiki highlighting, styled header with language label + copy button
- **Scrollbar theming:** Custom webkit scrollbar colors from theme
- **Selection color:** `::selection` styled per theme
- **kbd styling:** Per-theme keyboard hint styling (beveled/flat/outline)

---

## 4. Task Dispatch UX

### New WS Protocol Messages

```typescript
// Server → Client
| { type: 'task_start'; task_id: string; agent: string; description: string }
| { type: 'task_progress'; task_id: string; agent: string; status: AgentStatus; summary: string }
| { type: 'task_complete'; task_id: string; agent: string; result: 'success' | 'error'; summary: string; cost_usd: number }
```

### UI: Sidebar Task Tab

The sidebar gets two tabs: **Sessions** and **Tasks**. Toggle at the top.

Tasks tab shows live dispatched agents:

```
┌─ Tasks (3 active) ──────────┐
│                              │
│  ┌──────────────────────┐   │
│  │ [portrait] homelab    │   │  ← portrait animating per state
│  │ Checking Docker logs  │   │
│  │ 12s · $0.03          │   │
│  └──────────────────────┘   │
│                              │
│  ┌──────────────────────┐   │
│  │ [portrait] finance    │   │
│  │ Categorizing receipts │   │
│  │ 45s · $0.12          │   │
│  └──────────────────────┘   │
│                              │
│  ┌──────────────────────┐   │
│  │ [portrait] work  ✅   │   │
│  │ PR review complete    │   │
│  │ 2m · $0.08           │   │
│  └──────────────────────┘   │
└──────────────────────────────┘
```

### Interaction Model

- Click a task → chat panel switches to that agent's conversation stream
- Each agent's conversation is isolated — its messages, tool calls, confirm requests
- Main "general" chat is the default — routing happens there, agents fork off
- Interrupt targets a specific agent (button on each task card)
- Completed tasks show a summary card, expandable for full conversation

---

## 5. Implementation Sequencing

### Wave 1 — Foundation (parallelizable)
- **Theme engine:** types, registry, ThemeProvider, ops-cockpit default theme
- **Portrait system:** types, registry, renderers, AgentPortrait dispatcher
- **Bug fixes:** All 15 audit items (independent of theme/portrait work)

### Wave 2 — Integration
- **Apply theme to all components:** Refactor every component to use CSS variables only
- **Wire portrait system:** Replace current geometric portraits with registry-based rendering
- **Font loading:** IBM Plex for ops cockpit, verify loading works

### Wave 3 — Visual Polish
- **Welcome screen redesign:** Crow portrait, display font, agent cards
- **Atmospheric effects:** Grid overlay, scrollbar theming, selection colors, kbd styling
- **Error UI:** Inline error banners, toast notifications
- **Code block upgrade:** Theme-aware Shiki, copy button

### Wave 4 — Task Dispatch
- **Backend:** Add task_start/task_progress/task_complete WS messages
- **Frontend:** Sidebar task tab, task cards with live portraits, agent stream switching

### Wave 5 — Additional Themes
- **Retro Terminal theme:** Full implementation with scanlines, phosphor glow, pixel fonts
- **Dark Fantasy theme:** Full implementation with textures, gold borders, serif fonts

### Wave 6 — E2E Testing
- **Theme switching tests:** Verify CSS variable swap, font loading, localStorage persistence
- **Portrait rendering tests:** Each format type renders correctly at all sizes
- **Task dispatch tests:** Task lifecycle, agent stream switching, interrupt

---

## Non-Goals for Phase 2

- **Timeline view** — Phase 3 (needs trace API backend)
- **Inspector panel** — Phase 3
- **Memory mode** — Phase 3
- **Config mode / agent creation UI** — Phase 4
- **Command palette** — Phase 3
- **Responsive breakpoints below 1024px** — Phase 3
- **Light theme** — Phase 3 (each theme can have light/dark variants later)

---

## Success Criteria

1. Theme system works: switching between ops-cockpit and retro-terminal produces a completely different visual experience, not just a color swap
2. Portrait system works: can drop a sprite sheet, static image, or animated GIF for any agent and it renders correctly at all sizes with state-appropriate animation
3. The Corvus crow is a real character on the welcome screen, not a geometric circle
4. All 15 audit bugs are fixed
5. Zero hardcoded hex values in components — everything through CSS variables
6. Fonts load explicitly — no silent system font fallback
7. svelte-check: 0 errors, 0 warnings
8. All existing tests still pass + new tests for theme/portrait/task systems
