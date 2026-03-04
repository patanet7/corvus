<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentProfile, CapabilityHealth } from '$lib/api/agents';

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
		moduleHealthByName?: Record<string, CapabilityHealth>;
	}

	let { agent, profile = null, moduleHealthByName = {} }: Props = $props();

	const connectionModules = $derived.by(() => {
		if (profile) {
			const fromProfile = Object.keys(profile.moduleConfig);
			if (fromProfile.length > 0) return fromProfile;
		}
		return agent.toolModules ?? [];
	});

	function healthTone(status: string): string {
		switch (status) {
			case 'ok':
			case 'healthy':
			case 'connected':
				return 'border-success/40 text-success';
			case 'degraded':
				return 'border-warning/40 text-warning';
			case 'error':
			case 'offline':
			case 'unhealthy':
				return 'border-error/40 text-error';
			default:
				return 'border-border-muted text-text-muted';
		}
	}
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-sm font-medium text-text-primary">Connections</h4>
	<p class="mt-1 text-xs text-text-secondary">
		External capability modules exposed to this agent.
	</p>

	<div class="mt-3 space-y-2">
		{#if connectionModules.length === 0}
			<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px] text-text-muted">
				No external module connections configured.
			</div>
		{:else}
			{#each connectionModules as moduleName}
				{@const health = moduleHealthByName[moduleName]}
				{@const status = health?.status ?? (agent.runtimeStatus === 'offline' ? 'offline' : 'unknown')}
				<div class="flex items-center justify-between rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
					<div class="min-w-0 flex-1">
						<div class="font-mono text-text-primary">{moduleName}</div>
						{#if health?.message}
							<div class="truncate text-[10px] text-text-muted">{health.message}</div>
						{/if}
					</div>
					<span
						class="rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide {healthTone(status)}"
					>
						{status}
					</span>
				</div>
			{/each}
		{/if}
	</div>

	{#if profile}
		<div class="mt-2 rounded border border-border-muted bg-inset px-2 py-1 text-[10px] text-text-muted">
			Memory writes: {profile.canWriteMemory ? 'allowed' : 'blocked'} · Shared read:
			{profile.canReadShared ? 'allowed' : 'blocked'}
		</div>
	{/if}
</section>
