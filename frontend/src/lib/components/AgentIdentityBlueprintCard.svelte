<script lang="ts">
	import { isValidAgentName, type AgentInfo } from '$lib/types';
	import type { AgentProfile } from '$lib/api/agents';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
	}

	let { agent, profile = null }: Props = $props();

	const persona = $derived.by(() => {
		const value = profile?.metadata?.persona;
		return typeof value === 'string' && value.trim().length > 0 ? value : 'Professional and concise';
	});

	const portraitAgent = $derived(isValidAgentName(agent.id) ? agent.id : 'general');
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-xs uppercase tracking-wide text-text-muted">Identity Blueprint</h4>
	<div class="mt-2 flex items-start gap-3">
		<AgentPortrait
			agent={portraitAgent}
			status={agent.runtimeStatus === 'busy' ? 'thinking' : 'idle'}
			size="lg"
		/>
		<div class="min-w-0 flex-1 space-y-1">
			<div class="rounded border border-border-muted bg-inset px-2 py-1">
				<p class="text-[10px] uppercase tracking-wide text-text-muted">Agent Name</p>
				<p class="truncate text-sm text-text-primary">{agent.label}</p>
			</div>
			<div class="rounded border border-border-muted bg-inset px-2 py-1">
				<p class="text-[10px] uppercase tracking-wide text-text-muted">Role</p>
				<p class="text-xs text-text-secondary">{agent.description ?? profile?.description ?? 'Unspecified role'}</p>
			</div>
		</div>
	</div>
	<div class="mt-2 grid grid-cols-2 gap-2">
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<p class="text-[10px] uppercase tracking-wide text-text-muted">Tone</p>
			<p class="text-xs text-text-primary">{persona}</p>
		</div>
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<p class="text-[10px] uppercase tracking-wide text-text-muted">Portrait</p>
			<p class="font-mono text-xs text-text-secondary">{agent.id}</p>
		</div>
	</div>
</section>
