<script lang="ts">
	import type { ConnectionStatus } from '$lib/types';
	import { getThemeContext } from '$lib/themes/context';
	import AgentPortrait from './AgentPortrait.svelte';
	import AgentIdentityChip from './AgentIdentityChip.svelte';

	interface Props {
		connectionStatus: ConnectionStatus;
		activeAgent: string | null;
		sessionName: string;
		costUsd: number;
		tokensUsed: number;
		contextPct: number;
	}

	let {
		connectionStatus,
		activeAgent,
		sessionName,
		costUsd,
		tokensUsed,
		contextPct
	}: Props = $props();

	const themeCtx = getThemeContext();
	const separator = $derived(themeCtx.theme.components.statusBar.separator || '|');
	const statusBarFont = $derived(
		themeCtx.theme.components.statusBar.fontFamily === 'sans' ? 'var(--font-sans)' : 'var(--font-mono)'
	);
	const statusBarBg = $derived(themeCtx.theme.components.statusBar.background || 'var(--color-surface)');

	const hasSessionData = $derived(costUsd > 0 || tokensUsed > 0 || contextPct > 0);

	const statusDot = $derived(
		connectionStatus === 'connected'
			? 'bg-success'
			: connectionStatus === 'connecting'
				? 'bg-warning'
				: 'bg-error'
	);

	const statusLabel = $derived(
		connectionStatus === 'connected'
			? 'Connected'
			: connectionStatus === 'connecting'
				? 'Connecting...'
				: connectionStatus === 'error'
					? 'Connection failed'
					: 'Disconnected'
	);

	const contextColor = $derived(
		contextPct < 50 ? 'bg-success' : contextPct < 80 ? 'bg-warning' : 'bg-error'
	);
	const contextLabel = $derived(
		contextPct >= 98
			? 'Context Full'
			: contextPct >= 90
				? 'Context Critical'
				: contextPct >= 75
					? 'Context High'
					: 'Context Stable'
	);
</script>

<header
	class="flex items-center h-9 px-3 border-b border-border text-xs gap-3"
	style="background: {statusBarBg}; font-family: {statusBarFont};"
>
	<!-- Gateway status -->
	<div class="flex items-center gap-1.5" aria-live="polite">
		<span
			class="w-2 h-2 rounded-full {statusDot}"
			aria-hidden="true"
		></span>
		<span class="text-text-secondary">{statusLabel}</span>
	</div>

	<span class="text-text-muted" aria-hidden="true">{separator}</span>

	<!-- Session name -->
	<span class="text-text-muted">{sessionName}</span>

	<!-- Active agent -->
	{#if activeAgent}
		<span class="text-text-muted" aria-hidden="true">{separator}</span>
		<div class="flex items-center gap-1.5">
			<AgentPortrait agent={activeAgent} size="sm" />
			<AgentIdentityChip agent={activeAgent} />
		</div>
	{/if}

	<div class="flex-1"></div>

	<!-- Session metrics (only shown when data exists) -->
	{#if hasSessionData}
		<div class="flex items-center gap-1.5">
			<span class="text-text-primary tabular-nums"
				>${costUsd.toFixed(2)} / {tokensUsed.toLocaleString()} tok</span
			>
		</div>

		<span class="text-text-muted" aria-hidden="true">{separator}</span>

		<!-- Context meter -->
		<div class="flex items-center gap-1.5">
			<div
				class="w-16 h-1.5 bg-border-muted rounded-full overflow-hidden"
				role="progressbar"
				aria-valuenow={contextPct}
				aria-valuemin={0}
				aria-valuemax={100}
				aria-label="Context usage"
			>
				<div
					class="h-full rounded-full transition-all duration-300 {contextColor}"
					style="width: {Math.min(contextPct, 100)}%"
				></div>
			</div>
			<span class="text-text-primary tabular-nums">{contextPct.toFixed(0)}%</span>
			<span
				class="rounded border px-1 py-px text-[10px]
					{contextPct >= 90 ? 'border-error text-error' : contextPct >= 75 ? 'border-warning text-warning' : 'border-success text-success'}"
			>
				{contextLabel}
			</span>
		</div>
	{/if}
</header>
