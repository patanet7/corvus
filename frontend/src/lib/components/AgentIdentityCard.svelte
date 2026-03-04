<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentProfile } from '$lib/api/agents';

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
	}

	let { agent, profile = null }: Props = $props();

	const statusTone = $derived.by(() => {
		switch (agent.runtimeStatus) {
			case 'busy':
				return 'border-warning/40 text-warning';
			case 'offline':
				return 'border-error/40 text-error';
			case 'degraded':
				return 'border-info/40 text-info';
			default:
				return 'border-success/40 text-success';
		}
	});
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<div class="flex items-start justify-between gap-2">
		<div>
			<h4 class="text-sm font-medium text-text-primary">{agent.label}</h4>
			<p class="mt-1 text-xs text-text-secondary">
				{agent.description ?? profile?.description ?? 'No description configured.'}
			</p>
		</div>
		<span class="rounded border px-2 py-0.5 text-[10px] uppercase tracking-wide {statusTone}">
			{agent.runtimeStatus ?? 'active'}
		</span>
	</div>
	<div class="mt-3 grid gap-2 text-[11px] text-text-secondary sm:grid-cols-2">
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Queue</div>
			<div class="mt-1 text-text-primary">{agent.queueDepth ?? 0} active run(s)</div>
		</div>
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Runtime Model</div>
			<div class="mt-1 break-all text-text-primary">
				{agent.currentModel ?? profile?.resolvedModel ?? 'Router default'}
			</div>
		</div>
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Memory Domain</div>
			<div class="mt-1 text-text-primary">{agent.memoryDomain ?? profile?.memoryDomain ?? 'shared'}</div>
		</div>
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Complexity</div>
			<div class="mt-1 text-text-primary">{agent.complexity ?? profile?.complexity ?? 'medium'}</div>
		</div>
	</div>
</section>
