<script lang="ts">
	import StatusChip from './StatusChip.svelte';

	type MetricTone = 'neutral' | 'success' | 'warning' | 'error' | 'info';

	interface Props {
		title: string;
		value: string | number;
		subtitle?: string;
		deltaLabel?: string;
		tone?: MetricTone;
	}

	let { title, value, subtitle = '', deltaLabel = '', tone = 'neutral' }: Props = $props();
</script>

<article class="rounded border border-border-muted bg-surface px-3 py-2">
	<div class="flex items-center justify-between gap-2">
		<p class="text-[10px] uppercase tracking-wide text-text-muted">{title}</p>
		{#if deltaLabel}
			<StatusChip label={deltaLabel} tone={tone} />
		{/if}
	</div>
	<p class="mt-1 text-lg font-semibold tabular-nums text-text-primary">{value}</p>
	{#if subtitle}
		<p class="mt-1 text-[11px] text-text-secondary">{subtitle}</p>
	{/if}
</article>
