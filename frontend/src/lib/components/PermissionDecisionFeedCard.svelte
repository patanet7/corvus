<script lang="ts">
	import StatusChip from './primitives/StatusChip.svelte';

	export interface PermissionDecisionFeedRow {
		id: string;
		timestamp: string;
		agent: string;
		tool: string;
		state: 'allow' | 'deny' | 'confirm';
		scope?: string;
		reason?: string;
	}

	interface Props {
		events: PermissionDecisionFeedRow[];
		loading?: boolean;
		error?: string | null;
	}

	let { events, loading = false, error = null }: Props = $props();

	function toneFor(state: PermissionDecisionFeedRow['state']): 'success' | 'warning' | 'error' {
		if (state === 'allow') return 'success';
		if (state === 'confirm') return 'warning';
		return 'error';
	}
</script>

<section class="rounded border border-border-muted bg-surface px-3 py-3">
	<div class="flex items-center justify-between gap-2">
		<h4 class="text-xs uppercase tracking-wide text-text-muted">Permission Decisions</h4>
		<StatusChip label={`${events.length} rows`} uppercase={false} />
	</div>

	{#if loading}
		<div class="mt-2 text-xs text-text-muted">Loading permission decisions...</div>
	{:else if error}
		<div class="mt-2 rounded border border-error px-2 py-1 text-xs text-error">{error}</div>
	{:else if events.length === 0}
		<div class="mt-2 text-xs text-text-muted">No tool permission decisions in this run scope.</div>
	{:else}
		<div class="mt-2 max-h-[320px] space-y-1 overflow-y-auto">
			{#each events as event (event.id)}
				<div class="rounded border border-border-muted bg-inset px-2 py-1.5">
					<div class="flex flex-wrap items-center gap-2 text-[11px]">
						<span class="font-mono text-[10px] text-text-muted">{event.timestamp}</span>
						<span class="text-text-secondary">{event.agent}</span>
						<StatusChip label={event.state} tone={toneFor(event.state)} />
						<span class="text-text-primary">{event.tool}</span>
						{#if event.scope}
							<span class="rounded border border-border-muted px-1.5 py-0.5 text-[10px] text-text-muted">
								{event.scope}
							</span>
						{/if}
					</div>
					{#if event.reason}
						<p class="mt-1 text-[11px] text-text-muted">{event.reason}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</section>
