<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentProfile } from '$lib/api/agents';

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
	}

	let { agent, profile = null }: Props = $props();

	const moduleNames = $derived.by(() => {
		if (profile) {
			const names = Object.keys(profile.moduleConfig);
			if (names.length > 0) return names;
		}
		return agent.toolModules ?? [];
	});
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-sm font-medium text-text-primary">Tools + Permissions</h4>
	<p class="mt-1 text-xs text-text-secondary">
		Backend-defined tool permissions and confirmation gates.
	</p>

	<div class="mt-3 grid gap-2 sm:grid-cols-2">
		<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Builtin Tools</div>
			{#if profile && profile.builtinTools.length > 0}
				<div class="mt-1 flex flex-wrap gap-1">
					{#each profile.builtinTools as tool}
						<span class="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-primary">
							{tool}
						</span>
					{/each}
				</div>
			{:else}
				<div class="mt-1 text-text-muted">No explicit builtin tool list.</div>
			{/if}
		</div>

		<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Confirm-Gated</div>
			{#if profile && profile.confirmGatedTools.length > 0}
				<div class="mt-1 flex flex-wrap gap-1">
					{#each profile.confirmGatedTools as gated}
						<span class="rounded border border-warning/40 px-1.5 py-0.5 font-mono text-[10px] text-warning">
							{gated}
						</span>
					{/each}
				</div>
			{:else}
				<div class="mt-1 text-text-muted">No confirm gates configured.</div>
			{/if}
		</div>
	</div>

	<div class="mt-2 rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
		<div class="text-[10px] uppercase tracking-wide text-text-muted">Tool Modules</div>
		{#if moduleNames.length > 0}
			<div class="mt-1 flex flex-wrap gap-1">
				{#each moduleNames as moduleName}
					<span class="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-primary">
						{moduleName}
					</span>
				{/each}
			</div>
		{:else}
			<div class="mt-1 text-text-muted">No module-level tool access configured.</div>
		{/if}
	</div>
</section>
