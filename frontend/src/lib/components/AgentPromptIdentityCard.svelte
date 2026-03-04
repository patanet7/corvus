<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentProfile } from '$lib/api/agents';

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
	}

	let { agent, profile = null }: Props = $props();

	const promptReady = $derived(agent.hasPrompt ?? Boolean(profile?.promptFile));
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-sm font-medium text-text-primary">Soul + Prompt Identity</h4>
	<p class="mt-1 text-xs text-text-secondary">
		Agent identity is composed from soul prompt + agent prompt + routing model policy.
	</p>

	<div class="mt-3 space-y-2 text-[11px]">
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Prompt Source</div>
			<div class="mt-1 break-all text-text-primary">
				{profile?.promptFile ?? (promptReady ? 'Configured' : 'Fallback system prompt')}
			</div>
		</div>
		<div class="rounded border border-border-muted bg-inset px-2 py-1">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Model Strategy</div>
			<div class="mt-1 text-text-primary">
				{#if profile}
					{profile.autoModelRouting ? 'Auto routing enabled' : 'Manual model routing'}
					{#if profile.preferredModel}
						<div class="text-text-secondary">Preferred: <span class="font-mono">{profile.preferredModel}</span></div>
					{/if}
					{#if profile.fallbackModel}
						<div class="text-text-secondary">Fallback: <span class="font-mono">{profile.fallbackModel}</span></div>
					{/if}
				{:else}
					Waiting for profile payload...
				{/if}
			</div>
		</div>
		<div class="rounded border px-2 py-1 {promptReady ? 'border-success/40 text-success' : 'border-warning/40 text-warning'}">
			{promptReady
				? 'Prompt contract loaded from backend config.'
				: 'Prompt file missing; agent may be using generic fallback prompt.'}
		</div>
	</div>
</section>
