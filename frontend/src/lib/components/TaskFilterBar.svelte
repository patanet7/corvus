<script lang="ts">
	interface Props {
		search: string;
		statusOptions: string[];
		selectedStatuses: string[];
		agentOptions: string[];
		selectedAgents: string[];
		onSearchChange: (value: string) => void;
		onStatusToggle: (status: string) => void;
		onAgentToggle: (agent: string) => void;
		onClear: () => void;
	}

	let {
		search,
		statusOptions,
		selectedStatuses,
		agentOptions,
		selectedAgents,
		onSearchChange,
		onStatusToggle,
		onAgentToggle,
		onClear
	}: Props = $props();
</script>

<div class="rounded border border-border-muted bg-surface px-3 py-2">
	<div class="flex flex-wrap items-center gap-2">
		<input
			type="text"
			class="min-w-[200px] flex-1 rounded border border-border-muted bg-inset px-2 py-1 text-xs text-text-primary outline-none"
			placeholder="Search runs..."
			value={search}
			oninput={(event) => onSearchChange((event.currentTarget as HTMLInputElement).value)}
		/>
		<button
			type="button"
			class="rounded border border-border-muted px-2 py-1 text-[11px] text-text-secondary"
			onclick={onClear}
		>
			Clear
		</button>
	</div>

	{#if statusOptions.length > 0}
		<div class="mt-2 flex flex-wrap gap-1">
			<span class="text-[10px] uppercase tracking-wide text-text-muted">State</span>
			{#each statusOptions as status}
				<button
					type="button"
					class={`rounded border px-1.5 py-0.5 text-[10px] ${selectedStatuses.includes(status) ? 'border-focus bg-surface-raised text-text-primary' : 'border-border-muted text-text-muted'}`}
					onclick={() => onStatusToggle(status)}
				>
					{status}
				</button>
			{/each}
		</div>
	{/if}

	{#if agentOptions.length > 0}
		<div class="mt-1 flex flex-wrap gap-1">
			<span class="text-[10px] uppercase tracking-wide text-text-muted">Agent</span>
			{#each agentOptions as agent}
				<button
					type="button"
					class={`rounded border px-1.5 py-0.5 text-[10px] ${selectedAgents.includes(agent) ? 'border-focus bg-surface-raised text-text-primary' : 'border-border-muted text-text-muted'}`}
					onclick={() => onAgentToggle(agent)}
				>
					{agent}
				</button>
			{/each}
		</div>
	{/if}
</div>
