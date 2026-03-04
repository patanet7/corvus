<script lang="ts">
	import type { MemoryAgentInfo } from '$lib/api/memory';
	import StatusChip from '$lib/components/primitives/StatusChip.svelte';

	interface Props {
		agent: MemoryAgentInfo | null;
		loading?: boolean;
	}

	let { agent, loading = false }: Props = $props();
</script>

<div class="rounded border border-border-muted bg-surface p-3 text-xs">
	<div class="text-[10px] uppercase tracking-wide text-text-muted">Agent Context</div>
	{#if loading}
		<div class="mt-2 text-text-muted">Loading agent context...</div>
	{:else if !agent}
		<div class="mt-2 text-text-muted">No agent selected.</div>
	{:else}
		<div class="mt-2 space-y-2">
			<div class="flex items-center justify-between gap-2">
				<div class="text-sm font-semibold text-text-primary">{agent.label}</div>
				<StatusChip
					label={agent.canWrite ? 'write-enabled' : 'read-only'}
					tone={agent.canWrite ? 'success' : 'warning'}
					dot={true}
				/>
			</div>
			<div class="rounded border border-border-muted bg-inset px-2 py-2">
				<div class="text-[10px] uppercase tracking-wide text-text-muted">Memory Domain</div>
				<div class="mt-1 text-text-primary">{agent.memoryDomain}</div>
			</div>
			<div class="flex flex-wrap gap-1">
				<StatusChip
					label={agent.canReadShared ? 'shared-read' : 'no-shared-read'}
					tone={agent.canReadShared ? 'info' : 'warning'}
				/>
				{#each agent.readablePrivateDomains as domain (domain)}
					<StatusChip label={`private:${domain}`} tone="agent" uppercase={false} />
				{/each}
			</div>
		</div>
	{/if}
</div>
