<script lang="ts">
	import StatusChip from './primitives/StatusChip.svelte';

	export type TaskRunCardVariant = 'log-stream' | 'progress' | 'diff-preview';

	interface Props {
		variant: TaskRunCardVariant;
		title: string;
		agent: string;
		model?: string;
		status: 'running' | 'done' | 'error';
		elapsedLabel?: string;
		summary?: string;
		progressPct?: number;
		logLines?: string[];
		diffLines?: string[];
	}

	let {
		variant,
		title,
		agent,
		model = '',
		status,
		elapsedLabel = '',
		summary = '',
		progressPct = 0,
		logLines = [],
		diffLines = []
	}: Props = $props();

	const clampedProgress = $derived.by(() => Math.max(0, Math.min(100, progressPct)));

	const statusTone = $derived.by<'success' | 'warning' | 'error'>(() => {
		if (status === 'done') return 'success';
		if (status === 'error') return 'error';
		return 'warning';
	});
</script>

<article class="rounded border border-border-muted bg-surface p-3">
	<div class="flex items-start justify-between gap-2">
		<div class="min-w-0">
			<p class="truncate text-sm font-medium text-text-primary">{title}</p>
			<p class="text-[11px] text-text-secondary">{agent}{model ? ` • ${model}` : ''}</p>
		</div>
		<div class="flex items-center gap-1">
			<StatusChip label={status} tone={statusTone} />
			{#if elapsedLabel}
				<span class="font-mono text-[11px] text-text-muted">{elapsedLabel}</span>
			{/if}
		</div>
	</div>

	{#if summary}
		<p class="mt-2 text-xs text-text-secondary">{summary}</p>
	{/if}

	{#if variant === 'progress'}
		<div class="mt-2 rounded border border-border-muted bg-inset px-2 py-2">
			<div class="flex items-center justify-between text-[11px] text-text-muted">
				<span>Progress</span>
				<span>{clampedProgress}%</span>
			</div>
			<div class="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-raised">
				<div class="h-full bg-info" style={`width:${clampedProgress}%`}></div>
			</div>
		</div>
	{:else if variant === 'log-stream'}
		<div class="mt-2 max-h-28 overflow-y-auto rounded border border-border-muted bg-inset px-2 py-1 font-mono text-[10px] text-text-secondary">
			{#if logLines.length === 0}
				<p>No runtime logs yet.</p>
			{:else}
				{#each logLines as line, idx (`${title}-${idx}`)}
					<p>{line}</p>
				{/each}
			{/if}
		</div>
	{:else}
		<div class="mt-2 max-h-28 overflow-y-auto rounded border border-border-muted bg-inset px-2 py-1 font-mono text-[10px] text-text-secondary">
			{#if diffLines.length === 0}
				<p>No diff preview available.</p>
			{:else}
				{#each diffLines as line, idx (`${title}-diff-${idx}`)}
					<p class={line.startsWith('+') ? 'text-success' : line.startsWith('-') ? 'text-error' : ''}>
						{line}
					</p>
				{/each}
			{/if}
		</div>
	{/if}
</article>
