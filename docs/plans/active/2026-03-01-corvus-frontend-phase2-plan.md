---
title: "Corvus Frontend Phase 2 Implementation Plan"
type: plan
status: partially-implemented
date: 2026-03-01
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# Corvus Frontend Phase 2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the functional GitHub-dark chat MVP into a distinctive, themeable mission control with animated agent portraits, atmospheric effects, and multi-agent task dispatch.

**Architecture:** Theme-first — build a `ThemeProvider` that injects all visual tokens as CSS custom properties from `ThemeConfig` objects. Portraits and components read from these variables, never hardcoded hex values. The theme engine is the foundation everything else sits on. Portrait system is format-agnostic (SVG, sprite sheet, GIF, Lottie) with a renderer-dispatch pattern. Task dispatch adds a sidebar tab for monitoring parallel agent work.

**Tech Stack:** SvelteKit 2 + Svelte 5 runes, TailwindCSS 4 `@theme`, DOMPurify, marked, Shiki, Vitest + Playwright, pnpm.

**Reference docs:**
- `frontend/FUNDAMENTALS.md` — ground truth for all design decisions
- `docs/plans/2026-03-01-corvus-frontend-phase2-design.md` — full design spec

**Pre-conditions:** Phase 1 audit fixes are complete (DOMPurify, focus trap, `$derived.by`, `isValidAgentName`, dead button removal, IBM Plex fonts, message queue, etc.). All 19 unit + 18 E2E tests passing. 0 type errors.

---

## Wave 1: Theme Engine (Foundation)

### Task 1: Theme type definitions

**Files:**
- Create: `frontend/src/lib/themes/types.ts`
- Test: `frontend/src/lib/themes/themes.test.ts`

**Step 1: Write the type definitions**

```typescript
// frontend/src/lib/themes/types.ts
import type { AgentName } from '$lib/types';

export interface FontDef {
  family: string;
  weights: number[];
  source:
    | { type: 'google'; family: string }
    | { type: 'local'; files: Record<number, string> }
    | { type: 'system' };
  fallback: string;
}

export interface ThemeConfig {
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
    userMessageBg: string;
    agents: Record<AgentName, string>;
  };

  fonts: {
    sans: FontDef;
    mono: FontDef;
    display?: FontDef;
  };

  atmosphere: {
    backgroundEffect?: string;
    surfaceTexture?: string;
    borderStyle?: string;
    glowColor?: string;
    noiseOpacity?: number;
  };

  animations: {
    easing: string;
    durationScale: number;
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
      separator: string;
      fontFamily: 'mono' | 'sans';
    };
    modeRail: {
      iconWeight: number;
      activeIndicator: 'bar' | 'glow' | 'fill' | 'underline';
    };
    chatPanel: {
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
      shikiTheme: string;
      headerStyle: 'tab' | 'bar' | 'minimal' | 'none';
    };
    sidebar: {
      resizeHandle: 'native' | 'custom-bar' | 'hover-edge';
      activeSessionIndicator: 'left-border' | 'background' | 'glow';
    };
  };

  details: {
    borderRadius: string;
    scrollbarWidth: 'thin' | 'auto' | 'none';
    selectionBg: string;
    selectionText: string;
    kbdStyle: 'beveled' | 'flat' | 'outline';
  };
}
```

**Step 2: Write a test that validates the type is usable**

```typescript
// frontend/src/lib/themes/themes.test.ts
import { describe, it, expect } from 'vitest';
import type { ThemeConfig } from './types';

describe('ThemeConfig type', () => {
  it('can define a minimal theme config', () => {
    const config: ThemeConfig = { /* ops-cockpit values - see Task 2 */ } as ThemeConfig;
    expect(config.id).toBeDefined();
  });
});
```

**Step 3: Commit**

```
git add frontend/src/lib/themes/
git commit -m "feat(frontend): add ThemeConfig type definitions"
```

---

### Task 2: Ops Cockpit default theme

**Files:**
- Create: `frontend/src/lib/themes/themes/ops-cockpit.ts`
- Modify: `frontend/src/lib/themes/themes.test.ts`

**Step 1: Write the failing test**

```typescript
// Add to themes.test.ts
import { opsCockpit } from './themes/ops-cockpit';

describe('ops-cockpit theme', () => {
  it('has all required color keys', () => {
    expect(opsCockpit.colors.canvas).toBe('#0d1117');
    expect(opsCockpit.colors.agents.personal).toBe('#c084fc');
    expect(Object.keys(opsCockpit.colors.agents)).toHaveLength(9);
  });

  it('uses IBM Plex font family', () => {
    expect(opsCockpit.fonts.sans.family).toBe('IBM Plex Sans');
    expect(opsCockpit.fonts.mono.family).toBe('IBM Plex Mono');
  });

  it('has a valid id and name', () => {
    expect(opsCockpit.id).toBe('ops-cockpit');
    expect(opsCockpit.name).toBe('Modern Ops Cockpit');
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/themes/themes.test.ts`
Expected: FAIL — module not found

**Step 3: Write the ops-cockpit theme definition**

Create `frontend/src/lib/themes/themes/ops-cockpit.ts` with all values matching the current `app.css` `@theme` block. Every hex value from `app.css` lines 5-40 goes into `colors`. Font defs use `{ type: 'google', family: 'IBM Plex Sans' }`. Copy ALL current CSS custom property values verbatim — this is the canonical source of truth going forward.

Key values:
- `colors.canvas`: `#0d1117`, `colors.surface`: `#161b22`, etc. (exact values from app.css)
- `colors.userMessageBg`: `#1c2333`
- `colors.agents`: all 9 agent colors from app.css
- `fonts.sans`: IBM Plex Sans (400, 500, 600), Google Fonts source
- `fonts.mono`: IBM Plex Mono (400), Google Fonts source
- `fonts.display`: IBM Plex Sans Condensed (500, 600), Google Fonts source
- `atmosphere`: all empty/none (clean, no effects for this theme)
- `animations.easing`: `cubic-bezier(0.16, 1, 0.3, 1)`, `durationScale`: 1.0, `portraitStyle`: `'smooth'`
- `portraitFrame`: `shape: 'circle'`, subtle border, transparent bg
- `details.borderRadius`: `'4px'`, `scrollbarWidth`: `'thin'`, `kbdStyle`: `'flat'`
- `components.codeBlock.shikiTheme`: `'github-dark'`

**Step 4: Run test to verify it passes**

**Step 5: Commit**

```
git commit -m "feat(frontend): add ops-cockpit default theme definition"
```

---

### Task 3: Theme registry

**Files:**
- Create: `frontend/src/lib/themes/registry.ts`
- Modify: `frontend/src/lib/themes/themes.test.ts`

**Step 1: Write the failing tests**

```typescript
import { themeRegistry } from './registry';

describe('Theme registry', () => {
  it('has ops-cockpit registered by default', () => {
    const theme = themeRegistry.get('ops-cockpit');
    expect(theme).toBeDefined();
    expect(theme!.id).toBe('ops-cockpit');
  });

  it('lists all registered themes', () => {
    const themes = themeRegistry.list();
    expect(themes.length).toBeGreaterThanOrEqual(1);
    expect(themes.some(t => t.id === 'ops-cockpit')).toBe(true);
  });

  it('returns undefined for unknown theme id', () => {
    expect(themeRegistry.get('nonexistent')).toBeUndefined();
  });
});
```

**Step 2: Write the registry**

```typescript
// frontend/src/lib/themes/registry.ts
import type { ThemeConfig } from './types';
import { opsCockpit } from './themes/ops-cockpit';

const themes = new Map<string, ThemeConfig>();

function register(theme: ThemeConfig): void {
  themes.set(theme.id, theme);
}

function get(id: string): ThemeConfig | undefined {
  return themes.get(id);
}

function list(): ThemeConfig[] {
  return Array.from(themes.values());
}

// Register built-in themes
register(opsCockpit);

export const themeRegistry = { register, get, list };
```

**Step 3: Run tests, verify pass**

**Step 4: Commit**

```
git commit -m "feat(frontend): add theme registry with ops-cockpit default"
```

---

### Task 4: ThemeProvider component

**Files:**
- Create: `frontend/src/lib/themes/ThemeProvider.svelte`
- Modify: `frontend/src/routes/+layout.svelte` — wrap content in ThemeProvider
- Modify: `frontend/src/app.css` — change `@theme` to reference `--theme-*` CSS variables
- Test: E2E test that CSS variables are injected

**Step 1: Write the ThemeProvider**

The ThemeProvider component:
1. Reads `localStorage.getItem('corvus-theme')` on mount (default: `'ops-cockpit'`)
2. Resolves theme from registry
3. Injects all `colors.*` as `--color-*` CSS custom properties on `:root` via `document.documentElement.style.setProperty()`
4. Injects `--font-sans`, `--font-mono`, `--font-display` from font definitions
5. Builds Google Fonts URL from theme's font defs and injects a `<link>` element
6. Injects `--radius-default`, `--scrollbar-width` from `details`
7. Applies `atmosphere.backgroundEffect` as a `<div>` pseudo-overlay
8. Exposes `setTheme(id)` via Svelte context (`getContext`/`setContext`)
9. Saves theme choice to `localStorage` on change

Key implementation detail: The `@theme` block in `app.css` stays as-is — it provides the initial/default values. ThemeProvider *overrides* them via inline `:root` styles, which have higher specificity. This means the app works without JS (static render) using the hardcoded defaults, but ThemeProvider makes it dynamic.

**Step 2: Integrate into layout**

```svelte
<!-- frontend/src/routes/+layout.svelte -->
<script lang="ts">
  import '../app.css';
  import ThemeProvider from '$lib/themes/ThemeProvider.svelte';
  let { children } = $props();
</script>

<ThemeProvider>
  <div class="h-screen w-screen overflow-hidden bg-canvas text-text-primary">
    {@render children()}
  </div>
</ThemeProvider>
```

**Step 3: Write E2E test for theme injection**

```typescript
// Add to tests/e2e/chat.spec.ts or create tests/e2e/theme.spec.ts
test('ThemeProvider injects CSS variables on :root', async ({ page }) => {
  await page.goto('/');
  const canvas = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim()
  );
  expect(canvas).toBe('#0d1117');
});

test('IBM Plex Sans font link is loaded', async ({ page }) => {
  await page.goto('/');
  const links = await page.$$eval('link[href*="fonts.googleapis"]', els =>
    els.map(el => el.getAttribute('href'))
  );
  expect(links.some(l => l?.includes('IBM+Plex+Sans'))).toBe(true);
});
```

**Step 4: Run all tests (unit + E2E), verify pass**

**Step 5: Commit**

```
git commit -m "feat(frontend): add ThemeProvider with ops-cockpit defaults and localStorage persistence"
```

---

### Task 5: Theme context hook for components

**Files:**
- Create: `frontend/src/lib/themes/context.ts`
- Modify: `frontend/src/lib/themes/ThemeProvider.svelte` — set context
- Modify: `frontend/src/lib/themes/themes.test.ts` — add context tests

**Step 1: Create the context helper**

```typescript
// frontend/src/lib/themes/context.ts
import { getContext } from 'svelte';
import type { ThemeConfig } from './types';

const THEME_KEY = Symbol('corvus-theme');

export interface ThemeContext {
  theme: ThemeConfig;
  setTheme: (id: string) => void;
  themeId: string;
}

export function getTheme(): ThemeContext {
  return getContext<ThemeContext>(THEME_KEY);
}

export { THEME_KEY };
```

ThemeProvider sets this context. Components call `getTheme()` when they need the full config (e.g., for `components.codeBlock.shikiTheme` or `portraitFrame.shape`).

**Step 2: Wire into ThemeProvider's `setContext()`**

**Step 3: Write test that verifies context is usable**

**Step 4: Commit**

```
git commit -m "feat(frontend): add theme context hook for component access"
```

---

## Wave 2: Portrait System

### Task 6: Portrait type definitions + registry

**Files:**
- Create: `frontend/src/lib/portraits/types.ts`
- Create: `frontend/src/lib/portraits/registry.ts`
- Create: `frontend/src/lib/portraits/defaults.ts` — migrate current geometric SVGs
- Test: `frontend/src/lib/portraits/portraits.test.ts`

**Step 1: Write the portrait type definitions**

```typescript
// frontend/src/lib/portraits/types.ts
import type { AgentName, AgentStatus } from '$lib/types';

export type AssetDef =
  | { type: 'sprite'; src: string; frameWidth: number; frameHeight: number; frameCount: number; fps: number }
  | { type: 'svg'; viewBox: string; paths: { d: string; fill?: string; stroke?: string; opacity?: number }[] }
  | { type: 'image'; src: string }
  | { type: 'animated'; src: string }
  | { type: 'lottie'; data: object };

export interface PortraitConfig {
  agent: AgentName;
  format: 'sprite' | 'svg' | 'image' | 'animated' | 'lottie';
  states: Partial<Record<AgentStatus, AssetDef>> & { idle: AssetDef };
  accentColor?: string;
}
```

**Step 2: Migrate current PORTRAITS from `portraits.ts` into `defaults.ts`**

Convert each agent's `PortraitDef` (bgPath + fgPath) into a `PortraitConfig` with `format: 'svg'` and `states: { idle: { type: 'svg', viewBox, paths } }`. This preserves the existing rendering while enabling the new system.

**Step 3: Create portrait registry**

```typescript
// frontend/src/lib/portraits/registry.ts
import type { AgentName } from '$lib/types';
import type { PortraitConfig } from './types';
import { DEFAULT_PORTRAITS } from './defaults';

const portraits = new Map<AgentName, PortraitConfig>();

// Initialize with defaults
for (const config of DEFAULT_PORTRAITS) {
  portraits.set(config.agent, config);
}

export function getPortrait(agent: AgentName): PortraitConfig {
  return portraits.get(agent) ?? DEFAULT_PORTRAITS.find(p => p.agent === agent)!;
}

export function registerPortrait(config: PortraitConfig): void {
  portraits.set(config.agent, config);
}
```

**Step 4: Write tests**

```typescript
describe('Portrait registry', () => {
  it('has all 9 agents registered by default', () => {
    for (const name of AGENT_NAMES) {
      expect(getPortrait(name)).toBeDefined();
    }
  });

  it('default portraits use svg format', () => {
    const p = getPortrait('general');
    expect(p.format).toBe('svg');
    expect(p.states.idle.type).toBe('svg');
  });

  it('custom portrait overrides default', () => {
    registerPortrait({
      agent: 'homelab',
      format: 'image',
      states: { idle: { type: 'image', src: '/portraits/homelab/idle.png' } }
    });
    expect(getPortrait('homelab').format).toBe('image');
  });
});
```

**Step 5: Commit**

```
git commit -m "feat(frontend): add portrait type definitions, registry, and default SVG portraits"
```

---

### Task 7: Portrait renderers

**Files:**
- Create: `frontend/src/lib/portraits/renderers/SvgRenderer.svelte`
- Create: `frontend/src/lib/portraits/renderers/ImageRenderer.svelte`
- Create: `frontend/src/lib/portraits/renderers/SpriteRenderer.svelte`
- Create: `frontend/src/lib/portraits/renderers/AnimatedRenderer.svelte`

Each renderer receives an `AssetDef` of its type, a `size` (px number), and an `agentColor` (string). It renders the asset at the given size.

**Step 1: SvgRenderer** — extracts the current SVG rendering logic from `AgentPortrait.svelte`. Takes `{ type: 'svg', viewBox, paths }` and renders `<svg>` with the path list.

**Step 2: ImageRenderer** — simple `<img>` tag with `src`, `width`, `height`, `alt`, `object-fit: contain`.

**Step 3: SpriteRenderer** — `<div>` with CSS `background-image`, `background-position` animation using `steps()`. CSS custom properties for frame dimensions.

**Step 4: AnimatedRenderer** — `<img>` tag for GIF/APNG/WebP. Same as ImageRenderer but distinct component for semantic clarity and potential future controls (pause on `prefers-reduced-motion`).

Note: LottieRenderer is deferred — it requires `lottie-web` dependency. Create a placeholder that falls back to the SVG default.

**Step 5: Commit**

```
git commit -m "feat(frontend): add portrait renderers (SVG, image, sprite, animated)"
```

---

### Task 8: Refactor AgentPortrait as dispatcher

**Files:**
- Modify: `frontend/src/lib/components/AgentPortrait.svelte`
- Delete: `frontend/src/lib/portraits.ts` (old file — functionality moved to `portraits/`)
- Modify: All files that import from `$lib/portraits` (update import paths)

**Step 1: Rewrite AgentPortrait.svelte**

The new AgentPortrait:
1. Reads `PortraitConfig` from portrait registry for the given agent
2. Resolves the current state's `AssetDef` (fallback chain: current status → idle → accent-color initial)
3. Reads `portraitFrame` from theme context for frame styling (shape, border, glow)
4. Renders the appropriate sub-renderer inside a themed frame `<div>`

```svelte
<script lang="ts">
  import type { AgentName, AgentStatus } from '$lib/types';
  import { getPortrait } from '$lib/portraits/registry';
  import { getTheme } from '$lib/themes/context';
  import SvgRenderer from '$lib/portraits/renderers/SvgRenderer.svelte';
  import ImageRenderer from '$lib/portraits/renderers/ImageRenderer.svelte';
  import SpriteRenderer from '$lib/portraits/renderers/SpriteRenderer.svelte';
  import AnimatedRenderer from '$lib/portraits/renderers/AnimatedRenderer.svelte';

  interface Props {
    agent: AgentName;
    status?: AgentStatus;
    size?: 'sm' | 'md' | 'lg';
  }

  let { agent, status = 'idle', size = 'md' }: Props = $props();

  const sizes = { sm: 24, md: 32, lg: 48 };
  const px = $derived(sizes[size]);
  const config = $derived(getPortrait(agent));
  const asset = $derived(config.states[status] ?? config.states.idle);
  // Theme portrait frame comes from context (if available)
</script>
```

**Step 2: Update imports across codebase**

- `ChatPanel.svelte` line 4: `import AgentPortrait from './AgentPortrait.svelte'` — no change (same component name)
- `StatusBar.svelte` line 3: same — no change
- `+page.svelte`: no direct portrait import
- Remove old `portraits.ts` and `getAgentColor()` — colors now come from theme CSS variables

**Step 3: Verify all existing tests still pass**

Run: `cd frontend && npx vitest run && npx playwright test`

**Step 4: Commit**

```
git commit -m "refactor(frontend): AgentPortrait as format-agnostic renderer dispatcher"
```

---

## Wave 3: Component Theme Integration

### Task 9: Refactor all components to use only CSS variables

**Files:**
- Modify: `frontend/src/lib/components/StatusBar.svelte`
- Modify: `frontend/src/lib/components/ModeRail.svelte`
- Modify: `frontend/src/lib/components/ChatPanel.svelte`
- Modify: `frontend/src/lib/components/ToolCallCard.svelte`
- Modify: `frontend/src/lib/components/ConfirmCard.svelte`
- Modify: `frontend/src/lib/components/SessionSidebar.svelte`
- Modify: `frontend/src/lib/components/MessageContent.svelte`

**Goal:** Zero hardcoded hex values in any component. Every color, font, spacing, border-radius, and timing value references a CSS variable that the theme controls.

**Step 1: Audit each component for hardcoded values**

Search for: `#[0-9a-fA-F]`, `rgb(`, `rgba(`, hardcoded font names, hardcoded timing values, hardcoded border-radius values. Replace each with the appropriate CSS variable.

**Step 2: Add theme-aware component customization**

Where the theme's `components.*` config affects behavior (e.g., `components.codeBlock.shikiTheme`), read from theme context and apply. For the ops-cockpit theme, these should produce identical output to the current hardcoded values.

**Step 3: Verify visual parity**

After refactoring, the app must look IDENTICAL to the current state when using ops-cockpit theme. No visual regressions. Run E2E tests.

**Step 4: Commit**

```
git commit -m "refactor(frontend): eliminate all hardcoded visual values, use CSS variables only"
```

---

### Task 10: Font loading via ThemeProvider

**Files:**
- Modify: `frontend/src/lib/themes/ThemeProvider.svelte`
- Modify: `frontend/src/app.html` — remove hardcoded Google Fonts `<link>` (ThemeProvider handles it dynamically)

**Step 1: Dynamic font loading**

ThemeProvider builds a Google Fonts URL from the theme's `fonts.sans`, `fonts.mono`, and `fonts.display` definitions. It creates/updates a `<link>` element in `<head>` dynamically.

For the ops-cockpit theme, the generated URL should be identical to the current hardcoded one:
```
https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600&display=swap
```

**Step 2: Remove static font link from `app.html`**

The ThemeProvider now manages this. Remove the 3 `<link>` tags added in Phase 1 audit fixes.

**Step 3: Write E2E test**

```typescript
test('font link is dynamically loaded by ThemeProvider', async ({ page }) => {
  await page.goto('/');
  const fontLink = await page.$('link[href*="fonts.googleapis.com"]');
  expect(fontLink).not.toBeNull();
});
```

**Step 4: Commit**

```
git commit -m "feat(frontend): dynamic font loading via ThemeProvider, remove static font links"
```

---

## Wave 4: Visual Polish

### Task 11: Welcome screen redesign

**Files:**
- Modify: `frontend/src/lib/components/ChatPanel.svelte` — replace empty-state section
- Create: `frontend/static/portraits/general/` — crow portrait assets (or use enhanced SVG)

**Step 1: Redesign the welcome screen**

Replace the current welcome screen (lines 109-122 of ChatPanel.svelte):

Current:
```
[small general portrait]
Welcome to Corvus
Your messages are automatically routed...
[personal] [work] [homelab] ...  (text pills)
```

New design:
```
[LARGE animated general/crow portrait — lg+ size, breathing animation]

Welcome to Corvus                    ← uses --font-display
Your messages are routed to the right agent.

┌──────────┐  ┌──────────┐  ┌──────────┐
│ [portrait]│  │ [portrait]│  │ [portrait]│   ← agent cards with
│ personal  │  │   work   │  │ homelab  │      sm portraits + names
└──────────┘  └──────────┘  └──────────┘
┌──────────┐  ┌──────────┐  ┌──────────┐
│ [portrait]│  │ [portrait]│  │ [portrait]│
│ finance  │  │  email   │  │   docs   │
└──────────┘  └──────────┘  └──────────┘
         ┌──────────┐  ┌──────────┐
         │ [portrait]│  │ [portrait]│
         │  music   │  │   home   │
         └──────────┘  └──────────┘
```

Agent cards use `bg-surface-raised`, rounded corners from theme `details.borderRadius`, and subtle border. Each card shows the agent's portrait at sm size with its name below.

**Step 2: Use `--font-display` for the heading**

Add a Tailwind class or inline style for the "Welcome to Corvus" heading to use `font-family: var(--font-display)`.

**Step 3: Update E2E test for welcome screen**

Existing test checks for "Welcome to Corvus" text — should still pass. Add test for agent cards being visible.

**Step 4: Commit**

```
git commit -m "feat(frontend): redesigned welcome screen with crow portrait and agent cards"
```

---

### Task 12: Atmospheric effects + scrollbar theming

**Files:**
- Modify: `frontend/src/lib/themes/ThemeProvider.svelte`
- Modify: `frontend/src/app.css`

**Step 1: Background effect overlay**

ThemeProvider reads `atmosphere.backgroundEffect` and, if set, creates a fixed `<div>` overlay with `pointer-events: none`, `z-index: 1`, and the CSS value applied (e.g., a subtle grid pattern via `repeating-linear-gradient`). For ops-cockpit, this is `undefined` (no effect).

**Step 2: Scrollbar theming**

Add to `app.css`:
```css
::-webkit-scrollbar {
  width: var(--scrollbar-width, 8px);
}
::-webkit-scrollbar-track {
  background: var(--color-inset);
}
::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: var(--radius-default, 4px);
}
```

**Step 3: Selection color**

```css
::selection {
  background: var(--color-selection-bg, var(--color-info));
  color: var(--color-selection-text, white);
}
```

ThemeProvider sets `--color-selection-bg` and `--color-selection-text` from `theme.details`.

**Step 4: kbd styling per theme**

Add theme-aware kbd styles referencing `details.kbdStyle`. For ops-cockpit (flat): current styling. For retro (outline): monospace with border. For fantasy (beveled): box-shadow for 3D effect.

**Step 5: Commit**

```
git commit -m "feat(frontend): atmospheric effects, scrollbar theming, selection colors, themed kbd"
```

---

### Task 13: Code block copy button

**Files:**
- Modify: `frontend/src/lib/components/MessageContent.svelte`

**Step 1: Add copy button to code blocks**

In the `code()` renderer override (line 93 area), add a copy button to the `.code-block-header`:

```html
<div class="code-block-header">
  <span class="code-block-lang">{langLabel}</span>
  <button class="code-block-copy" onclick="navigator.clipboard.writeText(...)">
    Copy
  </button>
</div>
```

Since this is inside `{@html}`, the onclick needs to be wired via event delegation or a `$effect` that finds `.code-block-copy` buttons in the rendered DOM and attaches listeners.

**Implementation approach:** After `renderedHtml` is set, use a `$effect` that queries all `.code-block-copy` buttons within the `.prose-content` container and adds click handlers that read the adjacent `<pre>` text content and copy to clipboard.

**Step 2: Style the copy button**

Minimal: positioned right-aligned in the header, small monospace text, changes to "Copied!" for 2 seconds after click.

**Step 3: Read shikiTheme from theme context**

Replace hardcoded `'github-dark'` in `createHighlighter()` and `codeToHtml()` with the theme's `components.codeBlock.shikiTheme` value.

**Step 4: Commit**

```
git commit -m "feat(frontend): code block copy button and theme-aware Shiki highlighting"
```

---

### Task 14: Error UI — inline error banners + toast

**Files:**
- Create: `frontend/src/lib/components/ErrorBanner.svelte`
- Modify: `frontend/src/routes/+page.svelte` — surface errors as styled banners instead of plain markdown

**Step 1: Create ErrorBanner component**

A simple banner card with error styling:
```svelte
<div class="bg-[color-mix(in_srgb,var(--color-error)_10%,var(--color-surface))]
            border border-error rounded-lg p-3 text-sm">
  <div class="flex items-center gap-2">
    <svg ...error icon... />
    <span class="font-medium text-error">Error</span>
  </div>
  <p class="text-text-secondary mt-1">{message}</p>
</div>
```

**Step 2: Update +page.svelte error handling**

In the `'error'` case of `handleMessage`, instead of pushing a markdown `**Error:**` message, push a message with a flag like `isError: true`. ChatPanel renders error-flagged messages with the ErrorBanner component.

**Step 3: Connection toast**

When `connectionStatus` changes to `'error'` or `'disconnected'`, show a brief toast notification at the top of the chat panel. Auto-dismiss after 5 seconds or when connection recovers.

**Step 4: Commit**

```
git commit -m "feat(frontend): inline error banners and connection status toast"
```

---

## Wave 5: Task Dispatch UX

### Task 15: Task dispatch types + store

**Files:**
- Modify: `frontend/src/lib/types.ts` — add task-related message types
- Modify: `frontend/src/lib/stores.svelte.ts` — add task store
- Test: `frontend/src/lib/ws.test.ts` — add task message type tests

**Step 1: Add task message types to ServerMessage union**

```typescript
// Add to ServerMessage union in types.ts
| { type: 'task_start'; task_id: string; agent: string; description: string }
| { type: 'task_progress'; task_id: string; agent: string; status: AgentStatus; summary: string }
| { type: 'task_complete'; task_id: string; agent: string; result: 'success' | 'error'; summary: string; cost_usd: number }
```

**Step 2: Add Task interface**

```typescript
export interface Task {
  id: string;
  agent: AgentName;
  description: string;
  status: AgentStatus;
  summary: string;
  result?: 'success' | 'error';
  costUsd: number;
  startedAt: Date;
  completedAt?: Date;
  messages: ChatMessage[];
}
```

**Step 3: Add task store**

```typescript
// In stores.svelte.ts
export const taskStore = $state<{
  tasks: Map<string, Task>;
}>({ tasks: new Map() });
```

**Step 4: Write tests for new message types**

**Step 5: Commit**

```
git commit -m "feat(frontend): task dispatch types, store, and message protocol"
```

---

### Task 16: Handle task messages in +page.svelte

**Files:**
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/lib/stores.svelte.ts`

**Step 1: Wire task_start/progress/complete in handleMessage**

```typescript
case 'task_start': {
  const agent = isValidAgentName(msg.agent) ? msg.agent : 'general';
  taskStore.tasks.set(msg.task_id, {
    id: msg.task_id,
    agent,
    description: msg.description,
    status: 'thinking',
    summary: '',
    costUsd: 0,
    startedAt: new Date(),
    messages: []
  });
  break;
}
case 'task_progress': {
  const task = taskStore.tasks.get(msg.task_id);
  if (task) {
    task.status = msg.status;
    task.summary = msg.summary;
  }
  break;
}
case 'task_complete': {
  const task = taskStore.tasks.get(msg.task_id);
  if (task) {
    task.status = 'done';
    task.result = msg.result;
    task.summary = msg.summary;
    task.costUsd = msg.cost_usd;
    task.completedAt = new Date();
  }
  break;
}
```

**Step 2: Commit**

```
git commit -m "feat(frontend): wire task dispatch messages in page handler"
```

---

### Task 17: TaskSidebar component

**Files:**
- Create: `frontend/src/lib/components/TaskSidebar.svelte`

**Step 1: Build the TaskSidebar**

Mirrors `SessionSidebar` structure but shows live tasks:

```
┌─ Tasks (N active) ─────────┐
│                              │
│  [TaskCard]                  │  ← each task as a card
│  [TaskCard]                  │
│  [TaskCard ✅]               │  ← completed tasks
│                              │
└──────────────────────────────┘
```

Each TaskCard shows:
- Agent portrait (sm, animated per task status)
- Task description (truncated)
- Elapsed time (live counter) + cost
- Status indicator (running spinner, success check, error X)
- Click → switches chat panel to that agent's message stream (future)

**Step 2: Commit**

```
git commit -m "feat(frontend): TaskSidebar component with live task cards"
```

---

### Task 18: Wire Tasks mode in page layout

**Files:**
- Modify: `frontend/src/lib/components/ModeRail.svelte` — enable Tasks mode
- Modify: `frontend/src/routes/+page.svelte` — render TaskSidebar when mode is 'tasks'

**Step 1: Enable Tasks mode**

In ModeRail, change `{ id: 'tasks', label: 'Tasks', enabled: false }` to `enabled: true`.

**Step 2: Render TaskSidebar + ChatPanel in tasks mode**

```svelte
{#if activeMode === 'chat'}
  <SessionSidebar ... />
  <ChatPanel ... />
{:else if activeMode === 'tasks'}
  <TaskSidebar tasks={taskStore.tasks} />
  <ChatPanel ... />
{/if}
```

**Step 3: Update E2E tests**

Change the "Tasks button is disabled" test to "Tasks button is enabled and switches mode".

**Step 4: Commit**

```
git commit -m "feat(frontend): enable Tasks mode with TaskSidebar in page layout"
```

---

## Wave 6: Additional Themes

### Task 19: Retro Terminal theme

**Files:**
- Create: `frontend/src/lib/themes/themes/retro-terminal.ts`
- Modify: `frontend/src/lib/themes/registry.ts` — register it
- Modify: `frontend/src/lib/themes/themes.test.ts`

**Step 1: Define the retro-terminal theme**

Key values from design doc:
- Font sans: `Share Tech Mono`, mono: `VT323`, display: `Press Start 2P` (all Google Fonts)
- Surface: pure black `#000000`
- Text: phosphor green `#33ff33` (primary), dim green `#1a991a` (secondary)
- Borders: 1px solid phosphor green
- Border radius: `0px`
- Agent colors: neon versions of the standard palette
- Atmosphere: CRT scanlines via repeating-linear-gradient + optional flicker animation
- Portrait frame: square, scanline overlay
- Code theme: custom (or `'vitesse-dark'` as close match)
- Noise opacity: `0.03` (CRT grain)
- Kbd style: `'outline'`
- Scrollbar: green on black

**Step 2: Write tests**

```typescript
describe('retro-terminal theme', () => {
  it('uses VT323 mono font', () => {
    expect(retroTerminal.fonts.mono.family).toBe('VT323');
  });
  it('has CRT scanline atmosphere', () => {
    expect(retroTerminal.atmosphere.backgroundEffect).toBeDefined();
  });
  it('has square portrait frame', () => {
    expect(retroTerminal.portraitFrame.shape).toBe('square');
  });
});
```

**Step 3: Commit**

```
git commit -m "feat(frontend): add retro-terminal theme"
```

---

### Task 20: Dark Fantasy theme

**Files:**
- Create: `frontend/src/lib/themes/themes/dark-fantasy.ts`
- Modify: `frontend/src/lib/themes/registry.ts` — register it
- Modify: `frontend/src/lib/themes/themes.test.ts`

**Step 1: Define the dark-fantasy theme**

Key values from design doc:
- Font sans: `EB Garamond` (serif!), mono: `Fira Code`, display: `Cinzel Decorative`
- Surface: textured dark `#1a1510` with warm undertones
- Text: warm parchment `#d4c5a9` (primary), `#8a7b65` (secondary)
- Borders: 2px ridge warm gold `#b8860b`
- Border radius: `2px`
- Agent colors: jewel-tone versions of the palette
- Atmosphere: parchment grain noise, warm candlelight glow
- Portrait frame: hexagon, ornate gold border
- Code theme: `'catppuccin-mocha'`
- Noise opacity: `0.05`
- Kbd style: `'beveled'`
- Scrollbar: ornate warm

**Step 2: Write tests, register, commit**

```
git commit -m "feat(frontend): add dark-fantasy theme"
```

---

### Task 21: Theme selector in Config mode

**Files:**
- Create: `frontend/src/lib/components/ConfigPanel.svelte`
- Modify: `frontend/src/lib/components/ModeRail.svelte` — enable Config mode
- Modify: `frontend/src/routes/+page.svelte` — render ConfigPanel

**Step 1: Build ConfigPanel with theme selector**

A simple panel showing:
- Current theme name + preview swatch
- List of available themes (from `themeRegistry.list()`)
- Click to switch (calls `setTheme(id)` from theme context)
- Theme previews: small color swatch cards showing canvas/surface/text/agent colors

**Step 2: Enable Config mode in ModeRail**

**Step 3: Wire in +page.svelte**

```svelte
{:else if activeMode === 'config'}
  <ConfigPanel />
{/if}
```

**Step 4: Write E2E test for theme switching**

```typescript
test('theme selector switches to retro-terminal', async ({ page }) => {
  await page.goto('/');
  // Navigate to config mode
  await page.getByRole('button', { name: 'Config' }).click();
  // Click retro-terminal theme
  await page.getByText('Retro Terminal').click();
  // Verify CSS variable changed
  const canvas = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim()
  );
  expect(canvas).toBe('#000000');
});
```

**Step 5: Commit**

```
git commit -m "feat(frontend): Config mode with theme selector"
```

---

## Wave 7: E2E Test Coverage

### Task 22: Comprehensive E2E tests

**Files:**
- Create: `frontend/tests/e2e/theme.spec.ts`
- Create: `frontend/tests/e2e/portraits.spec.ts`
- Modify: `frontend/tests/e2e/chat.spec.ts` — update for visual changes

**Step 1: Theme E2E tests**

```typescript
test.describe('Theme System', () => {
  test('default theme is ops-cockpit', async ({ page }) => { ... });
  test('theme persists across page reload via localStorage', async ({ page }) => { ... });
  test('switching theme updates all CSS variables', async ({ page }) => { ... });
  test('font link updates when theme changes', async ({ page }) => { ... });
  test('prefers-reduced-motion disables atmosphere effects', async ({ page }) => { ... });
});
```

**Step 2: Portrait E2E tests**

```typescript
test.describe('Portrait System', () => {
  test('welcome screen shows all agent portraits', async ({ page }) => { ... });
  test('agent portraits render at correct sizes', async ({ page }) => { ... });
  test('portrait frame shape matches theme', async ({ page }) => { ... });
});
```

**Step 3: Update existing chat tests**

The "settings button" test was already removed (Phase 1 audit). Verify all 18 existing tests still pass with the visual overhaul. Update any selectors that changed.

**Step 4: Commit**

```
git commit -m "test(frontend): comprehensive E2E tests for theme and portrait systems"
```

---

### Task 23: Unit test coverage

**Files:**
- Modify: `frontend/src/lib/themes/themes.test.ts`
- Modify: `frontend/src/lib/portraits/portraits.test.ts`
- Modify: `frontend/src/lib/ws.test.ts`

**Step 1: Theme unit tests**

- All 3 themes pass validation (all required keys present, valid colors, valid font defs)
- Registry lists all registered themes
- Theme switching updates active theme

**Step 2: Portrait unit tests**

- All 9 agents have default portraits
- Custom portraits override defaults
- Fallback chain works (missing state → idle → accent color initial)

**Step 3: Protocol unit tests**

- Task message types are valid ServerMessage instances
- Task interface has required fields

**Step 4: Run full test suite, save results**

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
npx vitest run 2>&1 | tee "tests/output/frontend/${TIMESTAMP}_test_unit_results.log"
npx playwright test 2>&1 | tee "tests/output/frontend/${TIMESTAMP}_test_e2e_results.log"
```

**Step 5: Commit**

```
git commit -m "test(frontend): full unit test coverage for themes, portraits, and task protocol"
```

---

## Verification Checklist

After all tasks are complete, verify:

1. `pnpm run build` — clean static build, no errors
2. `npx vitest run` — all unit tests pass
3. `npx playwright test` — all E2E tests pass
4. `npx svelte-check --tsconfig ./tsconfig.json` — 0 errors, 0 warnings
5. Theme switching works: ops-cockpit ↔ retro-terminal ↔ dark-fantasy
6. Each theme produces a visually distinct experience (not just a color swap)
7. Portrait system renders SVG defaults correctly at all sizes
8. Tasks mode shows sidebar and enables the mode button
9. Zero hardcoded hex values in components (grep for `#[0-9a-fA-F]{3,8}` in `.svelte` files)
10. `prefers-reduced-motion` kills all animations
11. Focus rings are 2px everywhere
12. All `{@html}` content goes through DOMPurify

---

## Task Dependency Graph

```
Wave 1: Theme Engine
  Task 1 (types) → Task 2 (ops-cockpit) → Task 3 (registry) → Task 4 (ThemeProvider) → Task 5 (context)

Wave 2: Portrait System (can start after Task 1)
  Task 6 (types+registry) → Task 7 (renderers) → Task 8 (AgentPortrait refactor)

Wave 3: Integration (needs Tasks 5 + 8)
  Task 9 (component refactor) + Task 10 (font loading)

Wave 4: Visual Polish (needs Task 9)
  Task 11 (welcome) | Task 12 (atmosphere) | Task 13 (code blocks) | Task 14 (error UI)
  ↑ all parallelizable

Wave 5: Task Dispatch (can start after Task 5)
  Task 15 (types) → Task 16 (handler) → Task 17 (TaskSidebar) → Task 18 (wire mode)

Wave 6: Additional Themes (needs Task 5)
  Task 19 (retro) | Task 20 (fantasy) → Task 21 (selector)

Wave 7: Tests (after everything)
  Task 22 (E2E) | Task 23 (unit)
```

Tasks within the same wave are often parallelizable (marked with `|`).
