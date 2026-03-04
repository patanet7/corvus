<script lang="ts">
	import type { AgentInfo } from '$lib/types';

	interface Props {
		agent: AgentInfo;
		compact?: boolean;
	}

	let { agent, compact = false }: Props = $props();

	const modules = $derived(agent.toolModules ?? []);
	const visibleModules = $derived(compact ? modules.slice(0, 3) : modules);
	const hiddenCount = $derived(Math.max(0, modules.length - visibleModules.length));

	const complexityTone = $derived.by(() => {
		switch (agent.complexity) {
			case 'high':
				return 'border-warning text-warning';
			case 'low':
				return 'border-info text-info';
			default:
				return 'border-success text-success';
		}
	});
</script>

<div class="flex flex-wrap items-center gap-1 text-[10px]">
	{#if agent.complexity}
		<span class="rounded border px-1.5 py-0.5 uppercase {complexityTone}">
			{agent.complexity}
		</span>
	{/if}
	{#if agent.memoryDomain}
		<span class="rounded border border-border-muted px-1.5 py-0.5 text-text-secondary">
			memory:{agent.memoryDomain}
		</span>
	{/if}
	{#if modules.length > 0}
		{#each visibleModules as module}
			<span class="rounded border border-border px-1.5 py-0.5 text-text-primary">
				{module}
			</span>
		{/each}
		{#if hiddenCount > 0}
			<span class="rounded border border-border-muted px-1.5 py-0.5 text-text-muted">
				+{hiddenCount}
			</span>
		{/if}
	{:else}
		<span class="rounded border border-border-muted px-1.5 py-0.5 text-text-muted">
			no specialty tools
		</span>
	{/if}
	{#if agent.hasPrompt !== undefined}
		<span
			class="rounded border px-1.5 py-0.5 {agent.hasPrompt
				? 'border-success text-success'
				: 'border-warning text-warning'}"
		>
			{agent.hasPrompt ? 'prompted' : 'fallback prompt'}
		</span>
	{/if}
</div>
