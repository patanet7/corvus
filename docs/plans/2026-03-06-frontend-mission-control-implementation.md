# Frontend Mission Control Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the Corvus frontend from prototype scaffolding into a polished mission-control interface with three-panel layout, animated agent portraits, prominent agent/dispatch controls, and live operational awareness — across all 4 themes.

**Architecture:** Restructure +page.svelte to a three-column layout (mode rail + left panel + content + right inspector). Make agent selection and dispatch mode first-class clickable UI elements. Upgrade AgentPortrait animations to 6 expressive states with per-theme keyframes. Add InspectorPanel with live session stats, agent card, sub-agent tree, and trace feed. Remove hardcoded AGENT_NAMES, derive from backend.

**Tech Stack:** SvelteKit 5, Svelte 5 runes ($state/$derived), TailwindCSS 4 + CSS custom properties, TypeScript, WebSocket, Vite

---

## Slice 1: Layout + Dynamic Agents + Prominent Controls

### Task 1: Remove hardcoded AGENT_NAMES — make agents fully dynamic

**Files:**
- Modify: `frontend/src/lib/types.ts`

**Step 1: Update types.ts to remove static AGENT_NAMES**

Replace the hardcoded array with a dynamic system. `AgentName` becomes `string` since agents come from the backend at runtime.

```typescript
// REMOVE these lines (215-232):
// export const AGENT_NAMES = [ ... ] as const;
// export type AgentName = (typeof AGENT_NAMES)[number];
// export function isValidAgentName(name: string): name is AgentName { ... }

// REPLACE with:
export type AgentName = string;

/** Validate agent name against the live agent store. */
export function isValidAgentName(name: string, knownAgents?: AgentInfo[]): boolean {
	if (!knownAgents) return name.length > 0 && /^[a-z][a-z0-9_-]*$/.test(name);
	return knownAgents.some((a) => a.id === name);
}
```

**Step 2: Run frontend type check to find all breakages**

Run: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | head -60`
Expected: Type errors where `AgentName` was used as a literal union

**Step 3: Fix all type errors across components**

Components that import `AgentName` or `AGENT_NAMES`:
- `AgentPortrait.svelte` — change prop type to `agent: string`
- `AgentIdentityChip.svelte` — change prop type
- `ChatMessageList.svelte` — remove `AGENT_NAMES` import from welcome grid, use `agentStore.agents` instead
- `stores.svelte.ts` — update `currentSession.activeAgent` type
- `orchestrator.svelte.ts` — update references
- `ChatComposer.svelte` — update agent suggestion source
- All other files importing `AgentName` or `AGENT_NAMES`

For AgentPortrait: the `getPortrait(agent)` call in `portraits/registry.ts` needs a fallback for unknown agents — return a default crow silhouette portrait with neutral accent color.

For the welcome grid in ChatMessageList: change from filtering `AGENT_NAMES` to using the `availableAgents` prop (already passed as `AgentInfo[]`).

**Step 4: Run type check again**

Run: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | tail -5`
Expected: 0 errors

**Step 5: Run unit tests**

Run: `cd frontend && npm run test 2>&1 | tee ../tests/output/frontend/$(date +%Y%m%d_%H%M%S)_test_dynamic_agents_results.log | tail -10`
Expected: All pass

**Step 6: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/components/ frontend/src/lib/chat/ frontend/src/lib/stores.svelte.ts frontend/src/lib/portraits/
git commit -m "refactor: remove hardcoded AGENT_NAMES, derive agents from backend"
```

---

### Task 2: Add InspectorPanel component

**Files:**
- Create: `frontend/src/lib/components/InspectorPanel.svelte`

**Step 1: Create the inspector panel**

This is the right-side panel showing session stats, active agent card, and live metrics.

```svelte
<script lang="ts">
	import type { AgentInfo, AgentName, AgentStatus } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';
	import { getThemeContext } from '$lib/themes/context';

	interface Props {
		sessionId: string | null;
		activeAgent: AgentName | null;
		agentStatus: AgentStatus;
		agentInfo: AgentInfo | null;
		costUsd: number;
		tokensUsed: number;
		contextPct: number;
		contextLimit: number;
		selectedModel: string;
		messageCount: number;
		visible: boolean;
		onClose: () => void;
	}

	let {
		sessionId,
		activeAgent,
		agentStatus,
		agentInfo,
		costUsd,
		tokensUsed,
		contextPct,
		contextLimit,
		selectedModel,
		messageCount,
		visible,
		onClose
	}: Props = $props();

	const themeCtx = getThemeContext();

	const contextColor = $derived(
		contextPct < 50 ? 'var(--color-success)' : contextPct < 80 ? 'var(--color-warning)' : 'var(--color-error)'
	);
</script>

{#if visible}
	<aside
		class="flex flex-col w-[260px] min-w-[260px] border-l border-border bg-surface overflow-y-auto"
		style="font-family: var(--font-mono);"
	>
		<!-- Session Stats -->
		<section class="p-3 border-b border-border">
			<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Session</h3>
			<div class="grid grid-cols-2 gap-2 text-xs">
				<div>
					<span class="text-text-muted">Messages</span>
					<div class="text-text-primary tabular-nums">{messageCount}</div>
				</div>
				<div>
					<span class="text-text-muted">Cost</span>
					<div class="text-text-primary tabular-nums">${costUsd.toFixed(3)}</div>
				</div>
				<div>
					<span class="text-text-muted">Tokens</span>
					<div class="text-text-primary tabular-nums">{tokensUsed.toLocaleString()}</div>
				</div>
				<div>
					<span class="text-text-muted">Context</span>
					<div class="tabular-nums" style="color: {contextColor};">{contextPct.toFixed(1)}%</div>
				</div>
			</div>
			<!-- Context bar -->
			<div class="mt-2 w-full h-1.5 bg-border-muted rounded-full overflow-hidden">
				<div
					class="h-full rounded-full transition-all duration-300"
					style="width: {Math.min(contextPct, 100)}%; background: {contextColor};"
				></div>
			</div>
			<div class="mt-1 text-[10px] text-text-muted tabular-nums">
				{tokensUsed.toLocaleString()} / {contextLimit.toLocaleString()} tokens
			</div>
		</section>

		<!-- Active Agent Card -->
		{#if activeAgent && agentInfo}
			<section class="p-3 border-b border-border">
				<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Active Agent</h3>
				<div class="flex items-start gap-3">
					<AgentPortrait agent={activeAgent} status={agentStatus} size="lg" />
					<div class="flex-1 min-w-0">
						<div class="text-sm font-medium text-text-primary" style="color: var(--color-agent-{activeAgent});">
							@{activeAgent}
						</div>
						<div class="text-xs text-text-secondary mt-0.5">{agentInfo.label}</div>
						{#if agentInfo.description}
							<div class="text-[11px] text-text-muted mt-1 line-clamp-2">{agentInfo.description}</div>
						{/if}
					</div>
				</div>
				<!-- Model + Backend -->
				<div class="mt-2 flex flex-wrap gap-1">
					<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-surface-raised text-text-secondary border border-border-muted">
						{selectedModel}
					</span>
					{#if agentInfo.currentModel}
						<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-surface-raised text-text-muted border border-border-muted">
							{agentInfo.currentModel}
						</span>
					{/if}
				</div>
				<!-- Capabilities -->
				{#if agentInfo.toolModules && agentInfo.toolModules.length > 0}
					<div class="mt-2 flex flex-wrap gap-1">
						{#each agentInfo.toolModules as mod}
							<span class="px-1.5 py-0.5 rounded text-[10px] bg-canvas text-text-muted border border-border-muted">
								{mod}
							</span>
						{/each}
					</div>
				{/if}
			</section>
		{/if}

		<!-- Environment Health placeholder -->
		<section class="p-3 border-b border-border">
			<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Environment</h3>
			<div class="grid grid-cols-2 gap-2 text-xs">
				<div>
					<span class="text-text-muted">Gateway</span>
					<div class="flex items-center gap-1">
						<span class="w-1.5 h-1.5 rounded-full bg-success"></span>
						<span class="text-text-secondary">Online</span>
					</div>
				</div>
				<div>
					<span class="text-text-muted">Model</span>
					<div class="text-text-secondary truncate">{selectedModel || 'auto'}</div>
				</div>
			</div>
		</section>

		<!-- Close button at bottom -->
		<div class="p-2 mt-auto">
			<button
				class="w-full text-[10px] text-text-muted hover:text-text-secondary py-1 border border-border-muted rounded"
				onclick={onClose}
			>
				Hide Inspector
			</button>
		</div>
	</aside>
{/if}
```

**Step 2: Run type check**

Run: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | tail -5`
Expected: 0 errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/InspectorPanel.svelte
git commit -m "feat: add InspectorPanel component for right-side session/agent info"
```

---

### Task 3: Add AgentPickerStrip and DispatchModeToggle components

**Files:**
- Create: `frontend/src/lib/components/AgentPickerStrip.svelte`
- Create: `frontend/src/lib/components/DispatchModeToggle.svelte`

**Step 1: Create AgentPickerStrip**

Horizontal row of clickable agent portrait chips for the composer area.

```svelte
<script lang="ts">
	import type { AgentInfo, DispatchMode } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		agents: AgentInfo[];
		selectedRecipients: string[];
		dispatchMode: DispatchMode;
		onToggleAgent: (agentId: string) => void;
	}

	let { agents, selectedRecipients, dispatchMode, onToggleAgent }: Props = $props();

	const isSelected = (id: string) => selectedRecipients.includes(id);
</script>

<div class="flex items-center gap-1 overflow-x-auto py-1 px-1 scrollbar-thin">
	{#each agents.filter((a) => a.id !== 'huginn') as agent (agent.id)}
		<button
			class="flex items-center gap-1 px-2 py-1 rounded-full text-[11px] border transition-all duration-150 whitespace-nowrap
				{isSelected(agent.id)
					? 'border-current bg-surface-raised text-text-primary'
					: 'border-transparent text-text-muted hover:text-text-secondary hover:bg-surface-raised'}"
			style={isSelected(agent.id) ? `color: var(--color-agent-${agent.id}); border-color: var(--color-agent-${agent.id});` : ''}
			onclick={() => onToggleAgent(agent.id)}
			title={agent.description || agent.label}
		>
			<AgentPortrait agent={agent.id} size="sm" />
			<span>{agent.label || agent.id}</span>
		</button>
	{/each}
</div>
```

**Step 2: Create DispatchModeToggle**

Three-button toggle for Router / Direct / Parallel.

```svelte
<script lang="ts">
	import type { DispatchMode } from '$lib/types';

	interface Props {
		mode: DispatchMode;
		onChange: (mode: DispatchMode) => void;
	}

	let { mode, onChange }: Props = $props();

	const modes: Array<{ id: DispatchMode; label: string; title: string }> = [
		{ id: 'router', label: 'Router', title: 'Huginn auto-routes to the best agent' },
		{ id: 'direct', label: 'Direct', title: 'Send to selected agent only' },
		{ id: 'parallel', label: 'Parallel', title: 'Send to all selected agents simultaneously' }
	];
</script>

<div class="inline-flex rounded border border-border-muted overflow-hidden text-[10px]">
	{#each modes as m (m.id)}
		<button
			class="px-2.5 py-1 transition-colors duration-100
				{mode === m.id
					? 'bg-surface-raised text-text-primary border-border'
					: 'bg-transparent text-text-muted hover:text-text-secondary hover:bg-surface'}"
			class:border-r={m.id !== 'parallel'}
			class:border-border-muted={m.id !== 'parallel'}
			onclick={() => onChange(m.id)}
			title={m.title}
		>
			{m.label}
		</button>
	{/each}
</div>
```

**Step 3: Commit**

```bash
git add frontend/src/lib/components/AgentPickerStrip.svelte frontend/src/lib/components/DispatchModeToggle.svelte
git commit -m "feat: add AgentPickerStrip and DispatchModeToggle components"
```

---

### Task 4: Wire three-panel layout into +page.svelte

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

**Step 1: Import new components and add inspector state**

Add to the script section of +page.svelte:

```typescript
import InspectorPanel from '$lib/components/InspectorPanel.svelte';

let inspectorVisible = $state(true);

const activeAgentInfo = $derived.by(() => {
	const agent = currentSession.activeAgent;
	if (!agent) return null;
	return agentStore.agents.find((a) => a.id === agent) ?? null;
});
```

**Step 2: Update the template layout**

Replace the current layout structure. The key change is wrapping the content area and adding InspectorPanel as a sibling:

In the template, after the content area `{#if activeMode === 'chat' || activeMode === 'tasks'}` block and before the closing `</div>` of the flex container, add:

```svelte
{#if activeMode === 'chat' || activeMode === 'tasks'}
	<InspectorPanel
		sessionId={currentSession.id}
		activeAgent={currentSession.activeAgent}
		agentStatus={currentSession.agentStatus}
		agentInfo={activeAgentInfo}
		costUsd={currentSession.costUsd}
		tokensUsed={currentSession.tokensUsed}
		contextPct={currentSession.contextPct}
		contextLimit={200000}
		selectedModel={currentSession.selectedModel}
		messageCount={currentSession.messages.length}
		visible={inspectorVisible}
		onClose={() => { inspectorVisible = false; }}
	/>
{/if}
```

**Step 3: Add keyboard shortcut for inspector toggle**

In the onMount or a global keydown handler, add Cmd+Shift+I to toggle:

```typescript
function handleGlobalKeydown(e: KeyboardEvent) {
	if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'i') {
		e.preventDefault();
		inspectorVisible = !inspectorVisible;
	}
}
```

Add `svelte:window` listener in the template:
```svelte
<svelte:window onkeydown={handleGlobalKeydown} />
```

**Step 4: Run dev server and verify visually**

Run: `cd frontend && npm run dev`
Open http://localhost:5173 — verify:
- Right inspector panel visible in chat mode
- Shows session stats (messages, cost, tokens, context %)
- Shows active agent card when an agent is responding
- Cmd+Shift+I toggles it
- Themes still apply correctly

**Step 5: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "feat: wire three-panel layout with InspectorPanel"
```

---

### Task 5: Add AgentPickerStrip and DispatchModeToggle to ChatComposer

**Files:**
- Modify: `frontend/src/lib/components/ChatComposer.svelte`

**Step 1: Import and add new components above the textarea**

Add imports:
```typescript
import AgentPickerStrip from './AgentPickerStrip.svelte';
import DispatchModeToggle from './DispatchModeToggle.svelte';
```

Add above the textarea in the template — between the RecipientPicker and the input area:

```svelte
<!-- Agent picker + dispatch mode (always visible) -->
<div class="flex items-center gap-2 px-3 py-1 border-b border-border-muted">
	<DispatchModeToggle mode={dispatchMode} onChange={onDispatchModeChange} />
	{#if dispatchMode !== 'router'}
		<AgentPickerStrip
			agents={availableAgents}
			{selectedRecipients}
			{dispatchMode}
			onToggleAgent={(agentId) => {
				const current = [...selectedRecipients];
				const idx = current.indexOf(agentId);
				if (idx >= 0) {
					current.splice(idx, 1);
				} else {
					if (dispatchMode === 'direct') {
						// Direct mode: single selection
						onRecipientsChange([agentId], false);
						return;
					}
					current.push(agentId);
				}
				onRecipientsChange(current, false);
			}}
		/>
	{/if}
</div>
```

**Step 2: Verify visually**

Open http://localhost:5173 — verify:
- Dispatch mode toggle (Router/Direct/Parallel) visible above textarea
- When Direct or Parallel selected, agent chips appear
- Clicking an agent chip selects/deselects it
- Agent accent colors highlight selected agents
- Router mode hides the agent picker (auto-route)

**Step 3: Commit**

```bash
git add frontend/src/lib/components/ChatComposer.svelte
git commit -m "feat: add visible agent picker and dispatch mode toggle to composer"
```

---

### Task 6: Redesign welcome screen as live dashboard

**Files:**
- Modify: `frontend/src/lib/components/ChatMessageList.svelte`

**Step 1: Replace the sparse welcome screen**

Find the empty-state / welcome section in ChatMessageList.svelte (the block that renders when `messages.length === 0`). Replace the sparse agent circles with a rich dashboard.

The new welcome screen should show:
- Corvus branding header
- **Agent grid** — cards (not circles) from `availableAgents` prop with: portrait, name, label, status dot, model badge. Click card to pin that agent and start typing.
- **Recent sessions** — last 5 sessions (if passed as prop). Click to resume.
- **Quick stats** — connection status, agent count, model count.

Key: Use `availableAgents` (from `agentStore.agents`) NOT the removed `AGENT_NAMES` const.

Each agent card should use the agent's accent color as a subtle left border:
```svelte
<button
	class="flex items-start gap-3 p-3 rounded border border-border-muted bg-surface hover:bg-surface-raised transition-colors text-left w-full"
	style="border-left: 3px solid var(--color-agent-{agent.id});"
	onclick={() => onSelectAgent(agent.id)}
>
	<AgentPortrait agent={agent.id} size="md" />
	<div class="flex-1 min-w-0">
		<div class="text-sm font-medium text-text-primary">{agent.label || agent.id}</div>
		{#if agent.description}
			<div class="text-xs text-text-muted mt-0.5 line-clamp-2">{agent.description}</div>
		{/if}
		<div class="flex items-center gap-2 mt-1">
			{#if agent.currentModel}
				<span class="text-[10px] text-text-muted">{agent.currentModel}</span>
			{/if}
			{#if agent.toolModules && agent.toolModules.length > 0}
				<span class="text-[10px] text-text-muted">{agent.toolModules.length} tools</span>
			{/if}
		</div>
	</div>
</button>
```

**Step 2: Add onSelectAgent callback prop to ChatMessageList**

Add to Props interface and wire through ChatPanel → +page.svelte so clicking an agent card pins it and focuses the composer.

**Step 3: Verify visually with real backend data**

Open http://localhost:5173 — verify:
- Welcome screen shows agent cards with real data from backend
- Each card has the agent's accent color border
- Portraits animate (idle state)
- Clicking a card pins the agent
- Connection status shown
- Themes apply correctly to the cards

**Step 4: Commit**

```bash
git add frontend/src/lib/components/ChatMessageList.svelte frontend/src/lib/components/ChatPanel.svelte
git commit -m "feat: redesign welcome screen as live agent dashboard"
```

---

## Slice 2: Animated Portraits + Agent Identity

### Task 7: Upgrade AgentPortrait animations for all 6 states

**Files:**
- Modify: `frontend/src/lib/components/AgentPortrait.svelte`

**Step 1: Add awaiting_confirmation and done states**

Update the Props interface to support the new states:
```typescript
interface Props {
	agent: string;
	status?: 'idle' | 'thinking' | 'streaming' | 'done' | 'error' | 'awaiting_confirmation';
	size?: 'sm' | 'md' | 'lg';
}
```

**Step 2: Add new CSS keyframes and status classes**

Add to the `<style>` section:

```css
/* Done state — brief success flash */
.portrait-done {
	animation: done-flash 2s ease-out forwards;
}

.portrait-done::after {
	content: '';
	position: absolute;
	inset: 0;
	border-radius: var(--frame-radius, var(--radius-default));
	background: color-mix(in srgb, var(--color-success) 20%, transparent);
	animation: done-fade 2s ease-out forwards;
	pointer-events: none;
}

/* Awaiting confirmation — amber pulse */
.portrait-awaiting_confirmation {
	animation: confirm-pulse 1s ease-in-out infinite;
}

.portrait-awaiting_confirmation::after {
	content: '!';
	position: absolute;
	top: -2px;
	right: -2px;
	width: 12px;
	height: 12px;
	border-radius: 50%;
	background: var(--color-warning);
	color: var(--color-canvas);
	font-size: 8px;
	font-weight: bold;
	display: flex;
	align-items: center;
	justify-content: center;
	line-height: 1;
}

/* Enhanced thinking — sonar rings */
.portrait-thinking {
	animation: thinking-sonar var(--duration-thinking, 1500ms) var(--ease-in-out-sine) infinite;
}

/* Enhanced streaming — data flow arc */
.portrait-streaming {
	box-shadow: 0 0 8px color-mix(in srgb, var(--agent-color) 40%, transparent);
}

.portrait-streaming::before {
	content: '';
	position: absolute;
	inset: -3px;
	border-radius: inherit;
	border: 2px solid transparent;
	border-top-color: var(--agent-color);
	animation: stream-arc 1.2s linear infinite;
	pointer-events: none;
}

@keyframes done-flash {
	0% { box-shadow: 0 0 12px color-mix(in srgb, var(--color-success) 50%, transparent); }
	100% { box-shadow: none; }
}

@keyframes done-fade {
	0% { opacity: 1; }
	100% { opacity: 0; }
}

@keyframes confirm-pulse {
	0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-warning) 40%, transparent); }
	50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-warning) 0%, transparent); }
}

@keyframes thinking-sonar {
	0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--agent-color) 30%, transparent); }
	70% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--agent-color) 0%, transparent); }
	100% { box-shadow: 0 0 0 0 transparent; }
}

@keyframes stream-arc {
	0% { transform: rotate(0deg); }
	100% { transform: rotate(360deg); }
}

/* Stepped variants for retro themes */
.motion-stepped.portrait-done { animation-timing-function: steps(4, end); }
.motion-stepped.portrait-awaiting_confirmation { animation-timing-function: steps(4, end); }
.motion-stepped .portrait-streaming::before { animation-timing-function: steps(12, end); }

@media (prefers-reduced-motion: reduce) {
	.portrait-done,
	.portrait-awaiting_confirmation {
		animation: none;
	}
	.portrait-streaming::before,
	.portrait-done::after {
		animation: none;
	}
}
```

**Step 3: Update the statusClass derived to include new states**

```typescript
const statusClass = $derived(
	status === 'idle' ? 'portrait-idle'
		: status === 'thinking' ? 'portrait-thinking'
		: status === 'streaming' ? 'portrait-streaming'
		: status === 'done' ? 'portrait-done'
		: status === 'error' ? 'portrait-error'
		: status === 'awaiting_confirmation' ? 'portrait-awaiting_confirmation'
		: ''
);
```

**Step 4: Verify all 4 themes render animations differently**

Open http://localhost:5173. For each theme (ops-cockpit, retro-terminal, dark-fantasy, tactical-rts):
- Switch theme via config mode
- Start a chat to trigger agent states
- Verify: idle breathing, thinking sonar, streaming arc, done flash, error shake
- Verify retro themes use stepped animation timing

**Step 5: Commit**

```bash
git add frontend/src/lib/components/AgentPortrait.svelte
git commit -m "feat: upgrade portrait animations — 6 states with theme-aware keyframes"
```

---

### Task 8: Add per-message agent identity and metadata

**Files:**
- Modify: `frontend/src/lib/components/ChatMessageList.svelte`

**Step 1: Enhance assistant message rendering**

For each assistant message, add below the agent portrait:
- Agent name in accent color
- Model badge (small, muted)
- Expandable metadata row: click to show cost, tokens, latency, context delta

The message already has `msg.agent` and `msg.model` fields. Add visual elements:

```svelte
<!-- Inside each assistant message block -->
<div class="flex items-center gap-1.5 mb-1">
	<span
		class="text-xs font-medium"
		style="color: var(--color-agent-{msg.agent || 'general'});"
	>
		@{msg.agent || 'general'}
	</span>
	{#if msg.model}
		<span class="text-[10px] px-1 py-px rounded bg-surface-raised text-text-muted border border-border-muted">
			{msg.model}
		</span>
	{/if}
</div>
```

**Step 2: Commit**

```bash
git add frontend/src/lib/components/ChatMessageList.svelte
git commit -m "feat: add per-message agent identity chip with model badge"
```

---

## Slice 3: Live Operations

### Task 9: Add ContextMeter component (full-width)

**Files:**
- Create: `frontend/src/lib/components/ContextMeter.svelte`

**Step 1: Create the context meter**

A thin full-width progress bar that sits below the status bar, showing context consumption with color transitions and tooltip.

```svelte
<script lang="ts">
	interface Props {
		contextPct: number;
		tokensUsed: number;
		contextLimit: number;
		model: string;
	}

	let { contextPct, tokensUsed, contextLimit, model }: Props = $props();

	const color = $derived(
		contextPct < 50 ? 'var(--color-success)' : contextPct < 80 ? 'var(--color-warning)' : 'var(--color-error)'
	);

	const pulsing = $derived(contextPct >= 95);
</script>

<div
	class="w-full h-1 bg-border-muted relative"
	role="progressbar"
	aria-valuenow={contextPct}
	aria-valuemin={0}
	aria-valuemax={100}
	aria-label="Context window: {tokensUsed.toLocaleString()} / {contextLimit.toLocaleString()} tokens ({contextPct.toFixed(1)}%) — {model}"
	title="{tokensUsed.toLocaleString()} / {contextLimit.toLocaleString()} tokens ({contextPct.toFixed(1)}%) — {model}"
>
	<div
		class="h-full transition-all duration-500"
		class:animate-pulse={pulsing}
		style="width: {Math.min(contextPct, 100)}%; background: {color};"
	></div>
</div>
```

**Step 2: Wire into +page.svelte below StatusBar**

```svelte
<StatusBar ... />
<ContextMeter
	contextPct={currentSession.contextPct}
	tokensUsed={currentSession.tokensUsed}
	contextLimit={200000}
	model={currentSession.selectedModel}
/>
```

**Step 3: Commit**

```bash
git add frontend/src/lib/components/ContextMeter.svelte frontend/src/routes/+page.svelte
git commit -m "feat: add full-width ContextMeter below status bar"
```

---

### Task 10: Add SubAgentTree to InspectorPanel

**Files:**
- Create: `frontend/src/lib/components/SubAgentTree.svelte`
- Modify: `frontend/src/lib/components/InspectorPanel.svelte`

**Step 1: Create SubAgentTree component**

Renders a tree of dispatch -> runs when multi-agent routing occurs. Uses data from the task store.

```svelte
<script lang="ts">
	import type { Task } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		tasks: Task[];
	}

	let { tasks }: Props = $props();

	const activeTasks = $derived(
		tasks
			.filter((t) => t.status !== 'idle')
			.sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime())
			.slice(0, 10)
	);

	const statusDot = (status: string) =>
		status === 'done' ? 'bg-success'
		: status === 'error' ? 'bg-error'
		: status === 'streaming' || status === 'thinking' ? 'bg-warning'
		: 'bg-text-muted';
</script>

{#if activeTasks.length > 0}
	<section class="p-3 border-b border-border">
		<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Active Runs</h3>
		<div class="space-y-1.5">
			{#each activeTasks as task (task.id)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-1.5 h-1.5 rounded-full flex-shrink-0 {statusDot(task.status)}"></span>
					<AgentPortrait agent={task.agent} status={task.status} size="sm" />
					<span class="text-text-secondary truncate flex-1" style="color: var(--color-agent-{task.agent});">
						{task.agent}
					</span>
					<span class="text-[10px] text-text-muted tabular-nums">
						{task.phase || task.status}
					</span>
					{#if task.costUsd > 0}
						<span class="text-[10px] text-text-muted tabular-nums">${task.costUsd.toFixed(3)}</span>
					{/if}
				</div>
			{/each}
		</div>
	</section>
{/if}
```

**Step 2: Import and add to InspectorPanel**

Add `SubAgentTree` between the agent card and environment sections, passing `tasks` from task store.

**Step 3: Commit**

```bash
git add frontend/src/lib/components/SubAgentTree.svelte frontend/src/lib/components/InspectorPanel.svelte
git commit -m "feat: add SubAgentTree showing active runs in inspector"
```

---

### Task 11: Run full frontend test suite and verify with real backend

**Step 1: Run unit tests**

Run: `cd frontend && npm run test 2>&1 | tee ../tests/output/frontend/$(date +%Y%m%d_%H%M%S)_test_mission_control_results.log | tail -20`
Expected: All pass

**Step 2: Run type check**

Run: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | tail -10`
Expected: 0 errors

**Step 3: Visual verification with real backend**

Start backend: `ALLOWED_USERS=user uv run python -m corvus.server`
Start frontend: `cd frontend && CORVUS_DEV_REMOTE_USER=user npm run dev`
Open http://localhost:5173

Verify:
- [ ] Welcome dashboard shows real agent cards from backend
- [ ] Agent portraits have accent colors and idle animation
- [ ] Dispatch mode toggle visible (Router/Direct/Parallel)
- [ ] Agent picker appears in Direct/Parallel mode
- [ ] Right inspector shows session stats
- [ ] Context meter visible below status bar
- [ ] Send a real message — verify agent portrait animates through states
- [ ] Verify all 4 themes render correctly
- [ ] Cmd+Shift+I toggles inspector

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: frontend mission control overhaul — all slices complete"
```

---

## Dependency Order

```
Slice 1: Layout + Dynamic Agents (sequential)
  Task 1 (remove AGENT_NAMES) — foundational, must be first
  → Task 2 (InspectorPanel component)
  → Task 3 (AgentPickerStrip + DispatchModeToggle)
  → Task 4 (wire three-panel layout)
  → Task 5 (wire picker/toggle into composer)
  → Task 6 (redesign welcome screen)

Slice 2: Animated Portraits + Identity (after Task 1)
  Task 7 (upgrade portrait animations) — can start after Task 1
  → Task 8 (per-message agent identity)

Slice 3: Live Operations (after Task 4)
  Task 9 (ContextMeter) — after layout wired
  → Task 10 (SubAgentTree)
  → Task 11 (full verification)

Parallelizable: Slice 2 Tasks 7-8 can run in parallel with Slice 1 Tasks 2-6
```
