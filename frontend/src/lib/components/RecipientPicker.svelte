<script lang="ts">
	import type { AgentInfo, DispatchMode } from '$lib/types';

	interface Props {
		availableAgents: AgentInfo[];
		dispatchMode: DispatchMode;
		selectedRecipients: string[];
		sendToAll: boolean;
		onDispatchModeChange: (mode: DispatchMode) => void;
		onRecipientsChange: (recipients: string[], sendToAll: boolean) => void;
	}

	let {
		availableAgents,
		dispatchMode,
		selectedRecipients,
		sendToAll,
		onDispatchModeChange,
		onRecipientsChange
	}: Props = $props();

	let open = $state(false);

	function toggleAgent(agentId: string): void {
		const next = new Set(selectedRecipients);
		if (next.has(agentId)) {
			next.delete(agentId);
		} else {
			next.add(agentId);
		}
		onRecipientsChange(Array.from(next), false);
	}
</script>

<div class="mb-2 space-y-1">
	<div class="flex items-center gap-1 text-[10px] uppercase tracking-wide text-text-muted">
		<span class="rounded border border-border-muted px-1 py-0.5">Dispatch</span>
		<button
			type="button"
			class="rounded border px-1.5 py-0.5 transition-colors {dispatchMode === 'router'
				? 'border-focus text-text-primary bg-surface-raised'
				: 'border-border-muted text-text-secondary hover:text-text-primary'}"
			onclick={() => onDispatchModeChange('router')}
		>
			Router
		</button>
		<button
			type="button"
			class="rounded border px-1.5 py-0.5 transition-colors {dispatchMode === 'direct'
				? 'border-focus text-text-primary bg-surface-raised'
				: 'border-border-muted text-text-secondary hover:text-text-primary'}"
			onclick={() => onDispatchModeChange('direct')}
		>
			Direct
		</button>
		<button
			type="button"
			class="rounded border px-1.5 py-0.5 transition-colors {dispatchMode === 'parallel'
				? 'border-focus text-text-primary bg-surface-raised'
				: 'border-border-muted text-text-secondary hover:text-text-primary'}"
			onclick={() => onDispatchModeChange('parallel')}
		>
			Parallel
		</button>
	</div>

	<div class="relative">
		<div class="flex flex-wrap items-center gap-1">
			<button
				type="button"
				class="rounded border border-border-muted px-2 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-border hover:text-text-primary"
				onclick={() => (open = !open)}
			>
				Recipients
			</button>
			{#if sendToAll}
				<span class="rounded-full border border-info px-2 py-0.5 text-[11px] text-info">@all</span>
			{:else if selectedRecipients.length > 0}
				{#each selectedRecipients as recipient (recipient)}
					<span class="rounded-full border border-border px-2 py-0.5 text-[11px] text-text-primary"
						>@{recipient}</span
					>
				{/each}
			{:else}
				<span class="text-[11px] text-text-muted">No recipients selected (router decides)</span>
			{/if}
		</div>

		{#if open}
			<button
				class="fixed inset-0 z-20"
				type="button"
				aria-label="Close recipient picker"
				onclick={() => (open = false)}
			></button>
			<div
				class="absolute left-0 bottom-[calc(100%+0.25rem)] z-30 w-72 rounded-lg border border-border bg-surface shadow-lg"
			>
				<div class="border-b border-border-muted px-3 py-2 text-[11px] text-text-secondary">
					Choose one or more agents. `@all` fans out to all enabled agents.
				</div>
				<div class="max-h-52 overflow-y-auto p-2 space-y-1">
					<button
						type="button"
						class="flex w-full items-center justify-between rounded px-2 py-1 text-xs transition-colors
							{sendToAll
								? 'bg-surface-raised text-text-primary'
								: 'text-text-secondary hover:bg-surface-raised hover:text-text-primary'}"
						onclick={() => onRecipientsChange([], !sendToAll)}
					>
						<span>@all</span>
						<span>{sendToAll ? 'selected' : ''}</span>
					</button>
					{#each availableAgents as agent (agent.id)}
						<button
							type="button"
							class="flex w-full items-center justify-between rounded px-2 py-1 text-xs transition-colors
								{selectedRecipients.includes(agent.id) && !sendToAll
									? 'bg-surface-raised text-text-primary'
									: 'text-text-secondary hover:bg-surface-raised hover:text-text-primary'}"
							onclick={() => toggleAgent(agent.id)}
							disabled={sendToAll}
						>
							<span>@{agent.id}</span>
							<span>{selectedRecipients.includes(agent.id) && !sendToAll ? 'selected' : ''}</span>
						</button>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</div>
