<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentProfile } from '$lib/api/agents';
	import StatusChip from './primitives/StatusChip.svelte';

	export interface RoutingLane {
		id: string;
		label: string;
		purpose: string;
		model: string;
		fallbacks: string[];
		status?: 'healthy' | 'degraded' | 'offline';
	}

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
		lanes?: RoutingLane[];
	}

	let { agent, profile = null, lanes = [] }: Props = $props();

	const computedLanes = $derived.by<RoutingLane[]>(() => {
		if (lanes.length > 0) return lanes;
		const primary = profile?.preferredModel ?? profile?.resolvedModel ?? agent.currentModel ?? 'router default';
		const fallback = profile?.fallbackModel ?? 'none';
		return [
			{
				id: 'reasoning',
				label: 'Reasoning Core',
				purpose: 'Planning and deep analysis',
				model: primary,
				fallbacks: fallback === 'none' ? [] : [fallback],
				status: 'healthy'
			},
			{
				id: 'code',
				label: 'Code Synthesis',
				purpose: 'Implementation and refactor tasks',
				model: primary,
				fallbacks: fallback === 'none' ? [] : [fallback],
				status: 'healthy'
			},
			{
				id: 'rapid',
				label: 'Rapid Response',
				purpose: 'Quick turns and short checks',
				model: fallback === 'none' ? primary : fallback,
				fallbacks: [primary],
				status: fallback === 'none' ? 'degraded' : 'healthy'
			}
		];
	});

	function laneTone(status: RoutingLane['status']): 'success' | 'warning' | 'error' {
		switch (status) {
			case 'offline':
				return 'error';
			case 'degraded':
				return 'warning';
			default:
				return 'success';
		}
	}
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-xs uppercase tracking-wide text-text-muted">Model Routing</h4>
	<div class="mt-2 grid gap-2 md:grid-cols-3">
		{#each computedLanes as lane (lane.id)}
			<article class="rounded border border-border-muted bg-inset p-2">
				<div class="flex items-center justify-between gap-2">
					<p class="text-xs font-medium text-text-primary">{lane.label}</p>
					<StatusChip label={lane.status ?? 'healthy'} tone={laneTone(lane.status)} />
				</div>
				<p class="mt-1 text-[11px] text-text-muted">{lane.purpose}</p>
				<p class="mt-2 rounded border border-border-muted bg-surface px-1.5 py-1 font-mono text-[11px] text-text-secondary">
					{lane.model}
				</p>
				{#if lane.fallbacks.length > 0}
					<p class="mt-1 text-[10px] text-text-muted">
						Fallback: <span class="font-mono">{lane.fallbacks.join(', ')}</span>
					</p>
				{/if}
			</article>
		{/each}
	</div>
</section>
