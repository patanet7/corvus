<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentPolicyMatrix } from '$lib/api/agents';

	interface Props {
		agent: AgentInfo;
		policy?: AgentPolicyMatrix | null;
		loading?: boolean;
		error?: string | null;
	}

	let { agent, policy = null, loading = false, error = null }: Props = $props();

	function stateTone(state: string): string {
		switch (state) {
			case 'allow':
				return 'border-success/40 text-success';
			case 'confirm':
				return 'border-warning/40 text-warning';
			case 'deny':
				return 'border-error/40 text-error';
			default:
				return 'border-border-muted text-text-muted';
		}
	}
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-sm font-medium text-text-primary">Permissions Matrix</h4>
	<p class="mt-1 text-xs text-text-secondary">
		Explicit allow/confirm/deny policy for {agent.id}.
	</p>

	{#if loading}
		<div class="mt-3 rounded border border-border-muted bg-inset px-2 py-2 text-[11px] text-text-muted">
			Loading policy matrix...
		</div>
	{:else if error}
		<div class="mt-3 rounded border border-error/40 bg-surface-raised px-2 py-2 text-[11px] text-error">
			{error}
		</div>
	{:else if !policy || policy.entries.length === 0}
		<div class="mt-3 rounded border border-border-muted bg-inset px-2 py-2 text-[11px] text-text-muted">
			No policy entries available.
		</div>
	{:else}
		<div class="mt-3 flex flex-wrap gap-1 text-[10px]">
			<span class="rounded border border-border px-1.5 py-0.5 text-text-secondary">
				mode {policy.runtime.permissionMode}
			</span>
			<span class="rounded border border-border px-1.5 py-0.5 text-text-secondary">
				total {policy.summary.total}
			</span>
			<span class="rounded border border-success/40 px-1.5 py-0.5 text-success">
				allow {policy.summary.allow}
			</span>
			<span class="rounded border border-warning/40 px-1.5 py-0.5 text-warning">
				confirm {policy.summary.confirm}
			</span>
			<span class="rounded border border-error/40 px-1.5 py-0.5 text-error">
				deny {policy.summary.deny}
			</span>
		</div>
		<div class="mt-2 space-y-1">
			{#each policy.entries as entry (entry.key)}
				<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
					<div class="flex items-center gap-2">
						<span class="font-mono text-text-primary">{entry.subject}</span>
						<span class="rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide {stateTone(entry.state)}">
							{entry.state}
						</span>
						<span class="ml-auto text-[10px] text-text-muted">{entry.scope}</span>
					</div>
					<div class="mt-1 text-[10px] text-text-secondary">{entry.reason}</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
