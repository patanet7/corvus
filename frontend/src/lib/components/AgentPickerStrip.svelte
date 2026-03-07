<script lang="ts">
	import type { AgentInfo, DispatchMode } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		agents: AgentInfo[];
		selectedRecipients: string[];
		dispatchMode: DispatchMode;
		onToggleAgent: (agentId: string) => void;
	}

	let { agents, selectedRecipients, dispatchMode, onToggleAgent }: Props = $props();

	const isSelected = (id: string) => selectedRecipients.includes(id);
</script>

<div class="flex items-center gap-1 overflow-x-auto py-1 px-1 scrollbar-thin">
	{#each agents.filter((a) => a.id !== 'huginn') as agent (agent.id)}
		<button
			class="flex items-center gap-1 px-2 py-1 rounded-full text-[11px] border transition-all duration-150 whitespace-nowrap
				{isSelected(agent.id)
				? 'border-current bg-surface-raised text-text-primary'
				: 'border-transparent text-text-muted hover:text-text-secondary hover:bg-surface-raised'}"
			style={isSelected(agent.id)
				? `color: var(--color-agent-${agent.id}); border-color: var(--color-agent-${agent.id});`
				: ''}
			onclick={() => onToggleAgent(agent.id)}
			title={agent.description || agent.label}
		>
			<AgentPortrait agent={agent.id} size="sm" />
			<span>{agent.label || agent.id}</span>
		</button>
	{/each}
</div>
