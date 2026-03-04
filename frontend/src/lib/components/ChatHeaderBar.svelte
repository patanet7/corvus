<script lang="ts">
	import type { AgentName, AgentStatus, ModelInfo, AgentInfo } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';
	import AgentIdentityChip from './AgentIdentityChip.svelte';
	import AgentSpecialtyAccess from './AgentSpecialtyAccess.svelte';
	import LlmRuntimeStrip from './LlmRuntimeStrip.svelte';

	interface Props {
		activeAgent: AgentName | null;
		agentStatus: AgentStatus;
		sessionName: string;
		pinnedAgent: AgentName | null;
		activeAgentInfo: AgentInfo | null;
		selectedModel: string;
		models: ModelInfo[];
		contextPct: number;
		onClearPinnedAgent: () => void;
	}

	let {
		activeAgent,
		agentStatus,
		sessionName,
		pinnedAgent,
		activeAgentInfo,
		selectedModel,
		models,
		contextPct,
		onClearPinnedAgent
	}: Props = $props();

	const isStreaming = $derived(agentStatus === 'streaming' || agentStatus === 'thinking');
</script>

<div class="px-3 py-1 bg-surface border-b border-border-muted text-xs">
	<div class="flex items-center min-h-6">
		{#if activeAgent}
			<AgentPortrait agent={activeAgent} status={agentStatus} size="sm" />
			<span class="ml-1.5">
				<AgentIdentityChip agent={activeAgent} size="md" />
			</span>
		{:else}
			<AgentPortrait agent="general" size="sm" />
			<span class="ml-1.5 text-text-secondary">{sessionName}</span>
		{/if}

		{#if pinnedAgent}
			<span
				class="ml-2 inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[10px] text-text-secondary"
				title="Pinned agent for outgoing turns"
			>
				@{pinnedAgent}
				<button
					class="text-text-muted hover:text-text-primary"
					onclick={onClearPinnedAgent}
					aria-label="Clear pinned agent"
				>
					x
				</button>
			</span>
		{/if}

		{#if isStreaming}
			<span class="ml-auto text-xs text-warning animate-pulse">streaming...</span>
		{/if}
	</div>

	<div class="mt-1 flex flex-col gap-1">
		<LlmRuntimeStrip {selectedModel} {models} {contextPct} />
		{#if activeAgentInfo}
			<AgentSpecialtyAccess agent={activeAgentInfo} compact />
		{/if}
	</div>
</div>
