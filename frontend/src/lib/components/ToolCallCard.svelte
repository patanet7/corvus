<script lang="ts">
	import type { ToolCall } from '$lib/types';
	import { getThemeContext } from '$lib/themes/context';

	interface Props {
		toolCall: ToolCall;
		onOpenTrace?: (callId: string) => void;
	}

	let { toolCall, onOpenTrace }: Props = $props();
	const themeCtx = getThemeContext();
	const borderWidth = $derived(themeCtx.theme.components.toolCard.statusBorderWidth);
	const expandAnimation = $derived(themeCtx.theme.components.toolCard.expandAnimation);

	let expanded = $state(false);
	let showFullParams = $state(false);
	let showFullOutput = $state(false);

	const statusColor = $derived(
		toolCall.status === 'running'
			? 'var(--color-info)'
			: toolCall.status === 'success'
				? 'var(--color-success)'
				: 'var(--color-error)'
	);

	// Elapsed timer: show duration if complete, otherwise live timer
	let elapsedMs = $state(0);
	let startTime = $state(Date.now());

	$effect(() => {
		// Reset start time when this component mounts or status changes to running
		if (toolCall.status === 'running') {
			startTime = Date.now();
			const interval = setInterval(() => {
				elapsedMs = Date.now() - startTime;
			}, 100);
			return () => clearInterval(interval);
		}
	});

	const displayTime = $derived.by(() => {
		if (toolCall.status === 'running') {
			const seconds = (elapsedMs / 1000).toFixed(1);
			return `${seconds}s`;
		}
		if (toolCall.durationMs !== undefined) {
			const seconds = (toolCall.durationMs / 1000).toFixed(1);
			return `${seconds}s`;
		}
		return '';
	});

	const truncatedParams = $derived.by(() => {
		const json = JSON.stringify(toolCall.params, null, 2);
		if (json.length <= 200) return json;
		return json.slice(0, 200) + '...';
	});

	const fullParams = $derived.by(() => JSON.stringify(toolCall.params, null, 2));

	const truncatedOutput = $derived.by(() => {
		if (!toolCall.output) return '';
		if (toolCall.output.length <= 500) return toolCall.output;
		return toolCall.output.slice(0, 500) + '...';
	});

	function isParamsTruncated(): boolean {
		return fullParams.length > 200;
	}

	function isOutputTruncated(): boolean {
		return (toolCall.output?.length ?? 0) > 500;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			expanded = !expanded;
		}
	}
</script>

<div
	class="tool-call-card"
	style="--status-color: {statusColor}; --tool-border-width: {borderWidth};"
>
	<!-- Collapsed header — always visible -->
	<button
		class="tool-call-header"
		onclick={() => (expanded = !expanded)}
		onkeydown={handleKeydown}
		aria-expanded={expanded}
		aria-label="Tool call: {toolCall.tool}, status: {toolCall.status}"
	>
		<!-- Status icon -->
		<span class="tool-status-icon">
			{#if toolCall.status === 'running'}
				<svg class="spinner" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
					<circle cx="7" cy="7" r="5.5" stroke="var(--color-info)" stroke-width="1.5" stroke-dasharray="20 14" stroke-linecap="round" />
				</svg>
			{:else if toolCall.status === 'success'}
				<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
					<path d="M3 7.5L5.5 10L11 4" stroke="var(--color-success)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
				</svg>
			{:else}
				<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
					<path d="M4 4L10 10M10 4L4 10" stroke="var(--color-error)" stroke-width="1.5" stroke-linecap="round" />
				</svg>
			{/if}
		</span>

		<!-- Tool name -->
		<span class="tool-name">{toolCall.tool}</span>

		<!-- Elapsed time -->
		<span class="tool-elapsed">
			{#if toolCall.status === 'running'}
				running... {displayTime}
			{:else}
				{displayTime}
			{/if}
		</span>

		<!-- Expand chevron -->
		<span class="tool-chevron" class:tool-chevron-open={expanded}>
			<svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
				<path d="M4 5L6 7L8 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
			</svg>
		</span>
	</button>

	<!-- Expanded details -->
	{#if expanded}
		<div class="tool-call-details expand-{expandAnimation}">
			<div class="mb-2 flex flex-wrap items-center gap-1">
				<span class="rounded border border-border-muted px-1.5 py-0.5 text-[10px] text-text-muted">
					trace: {toolCall.callId}
				</span>
				{#if onOpenTrace}
					<button
						type="button"
						class="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
						onclick={() => onOpenTrace(toolCall.callId)}
					>
						Open Trace
					</button>
				{/if}
			</div>

			{#if Object.keys(toolCall.params).length > 0}
				<div class="tool-section">
					<div class="mb-1 flex items-center gap-2">
						<span class="tool-section-label mb-0">Parameters</span>
						{#if isParamsTruncated()}
							<button
								type="button"
								class="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
								onclick={() => (showFullParams = !showFullParams)}
							>
								{showFullParams ? 'Show Less' : 'Show Full'}
							</button>
						{/if}
					</div>
					<pre class="tool-section-content">{showFullParams ? fullParams : truncatedParams}</pre>
				</div>
			{/if}

			{#if toolCall.output}
				<div class="tool-section">
					<div class="mb-1 flex items-center gap-2">
						<span class="tool-section-label mb-0">Output</span>
						{#if isOutputTruncated()}
							<button
								type="button"
								class="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
								onclick={() => (showFullOutput = !showFullOutput)}
							>
								{showFullOutput ? 'Show Less' : 'Show Full'}
							</button>
						{/if}
					</div>
					<pre class="tool-section-content">{showFullOutput ? toolCall.output : truncatedOutput}</pre>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.tool-call-card {
		background: var(--color-surface-raised);
		border-left: var(--tool-border-width, 3px) solid var(--status-color);
		border-radius: var(--radius-default);
		margin: 4px 0;
		overflow: hidden;
	}

	.tool-call-header {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		height: 32px;
		padding: 0 8px;
		background: none;
		border: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		font-size: 12px;
		text-align: left;
		transition: background-color var(--duration-fast) ease;
	}

	.tool-call-header:hover {
		background: var(--color-overlay);
	}

	.tool-call-header:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: -1px;
	}

	.tool-status-icon {
		display: inline-flex;
		flex-shrink: 0;
	}

	.spinner {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}

	.tool-name {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.tool-elapsed {
		margin-left: auto;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-text-muted);
		white-space: nowrap;
	}

	.tool-chevron {
		display: inline-flex;
		color: var(--color-text-muted);
		transition: transform var(--duration-fast) ease;
		flex-shrink: 0;
	}

	.tool-chevron-open {
		transform: rotate(180deg);
	}

	.tool-call-details {
		padding: 8px 12px;
		border-top: 1px solid var(--color-border-muted);
	}

	.expand-slide {
		animation: expand-slide var(--duration-fast) var(--ease-out-expo, ease-out);
	}

	.expand-fade {
		animation: expand-fade var(--duration-fast) ease;
	}

	.expand-instant {
		animation: none;
	}

	@keyframes expand-slide {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	@keyframes expand-fade {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	.tool-section {
		margin-bottom: 8px;
	}

	.tool-section:last-child {
		margin-bottom: 0;
	}

	.tool-section-label {
		display: block;
		font-size: 10px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-muted);
		margin-bottom: 4px;
	}

	.tool-section-content {
		font-family: var(--font-mono);
		font-size: 11px;
		line-height: 1.5;
		color: var(--color-text-secondary);
		background: var(--color-inset);
		padding: 6px 8px;
		border-radius: var(--radius-default);
		overflow-x: auto;
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
	}

	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
</style>
