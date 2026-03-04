<script lang="ts">
	import MetricCard from './primitives/MetricCard.svelte';

	export interface TaskMetric {
		id: string;
		label: string;
		value: string | number;
		hint?: string;
		tone?: 'neutral' | 'success' | 'warning' | 'error' | 'info';
	}

	interface Props {
		metrics: TaskMetric[];
	}

	let { metrics }: Props = $props();
</script>

<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
	{#if metrics.length === 0}
		<MetricCard title="No Metrics" value="--" subtitle="No runtime dispatch metrics yet" />
	{:else}
		{#each metrics as metric (metric.id)}
			<MetricCard
				title={metric.label}
				value={metric.value}
				subtitle={metric.hint}
				tone={metric.tone}
			/>
		{/each}
	{/if}
</div>
