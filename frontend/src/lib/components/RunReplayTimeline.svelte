<script lang="ts">
	import type { RunEvent } from '$lib/api/agents';

	type EventFilter = 'all' | 'phase' | 'output' | 'tool' | 'control';

	interface Props {
		events: RunEvent[];
		loading?: boolean;
		error?: string | null;
	}

	let { events, loading = false, error = null }: Props = $props();
	let filter = $state<EventFilter>('all');

	function categoryFor(eventType: string): EventFilter {
		if (eventType === 'run_phase') return 'phase';
		if (eventType === 'run_output_chunk') return 'output';
		if (
			eventType === 'tool_start' ||
			eventType === 'tool_result' ||
			eventType === 'tool_permission_decision' ||
			eventType === 'confirm_request'
		) {
			return 'tool';
		}
		return 'control';
	}

	const visibleEvents = $derived.by(() => {
		if (filter === 'all') return events;
		return events.filter((event) => categoryFor(event.event_type) === filter);
	});

	function eventSummary(event: RunEvent): string {
		const payload = event.payload ?? {};
		if (event.event_type === 'run_phase') {
			const phase = typeof payload.phase === 'string' ? payload.phase : 'phase';
			const summary = typeof payload.summary === 'string' ? payload.summary : '';
			return summary ? `${phase}: ${summary}` : phase;
		}
		if (event.event_type === 'run_output_chunk') {
			const idx = typeof payload.chunk_index === 'number' ? payload.chunk_index : null;
			const final = payload.final === true;
			const content = typeof payload.content === 'string' ? payload.content : '';
			if (content) return idx !== null ? `#${idx} ${content}` : content;
			if (final) return idx !== null ? `#${idx} final marker` : 'final marker';
			return idx !== null ? `#${idx} empty chunk` : 'empty chunk';
		}
		if (event.event_type === 'tool_start') {
			return `Tool start: ${typeof payload.tool === 'string' ? payload.tool : 'tool'}`;
		}
		if (event.event_type === 'tool_result') {
			const status = typeof payload.status === 'string' ? payload.status : 'success';
			return `Tool result (${status})`;
		}
		if (event.event_type === 'tool_permission_decision') {
			const state =
				typeof payload.state === 'string' ? payload.state : payload.allowed === true ? 'allow' : 'deny';
			const tool = typeof payload.tool === 'string' ? payload.tool : 'tool';
			const reason = typeof payload.reason === 'string' ? payload.reason : '';
			return reason ? `Permission ${state}: ${tool} (${reason})` : `Permission ${state}: ${tool}`;
		}
		if (event.event_type === 'confirm_request') {
			return `Confirmation requested: ${typeof payload.tool === 'string' ? payload.tool : 'tool'}`;
		}
		if (event.event_type === 'run_complete') {
			const result = typeof payload.result === 'string' ? payload.result : 'done';
			const summary = typeof payload.summary === 'string' ? payload.summary : '';
			return summary ? `${result}: ${summary}` : result;
		}
		return event.event_type;
	}

	function badgeClasses(eventType: string): string {
		if (eventType === 'run_phase') return 'border-focus text-text-primary';
		if (eventType === 'run_output_chunk') return 'border-info text-info';
		if (
			eventType === 'tool_start' ||
			eventType === 'tool_result' ||
			eventType === 'tool_permission_decision' ||
			eventType === 'confirm_request'
		) {
			return 'border-warning text-warning';
		}
		if (eventType === 'run_complete') return 'border-success text-success';
		return 'border-border-muted text-text-muted';
	}
</script>

<section class="rounded border border-border-muted bg-surface px-3 py-2">
	<div class="flex items-center justify-between gap-2">
		<h4 class="text-xs uppercase tracking-wide text-text-muted">Run Replay</h4>
		<div class="flex items-center gap-1 text-[10px]">
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'all'
					? 'border-focus text-text-primary bg-surface-raised'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'all')}
			>
				All
			</button>
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'phase'
					? 'border-focus text-text-primary bg-surface-raised'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'phase')}
			>
				Phase
			</button>
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'output'
					? 'border-focus text-text-primary bg-surface-raised'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'output')}
			>
				Output
			</button>
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'tool'
					? 'border-focus text-text-primary bg-surface-raised'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'tool')}
			>
				Tools
			</button>
		</div>
	</div>

	{#if loading}
		<div class="mt-2 text-xs text-text-muted">Loading replay events...</div>
	{:else if error}
		<div class="mt-2 rounded border border-error px-2 py-1 text-xs text-error">{error}</div>
	{:else if visibleEvents.length === 0}
		<div class="mt-2 text-xs text-text-muted">No replay events in this filter.</div>
	{:else}
		<div class="mt-2 max-h-[380px] space-y-1 overflow-y-auto">
			{#each visibleEvents as event (event.id)}
				<details class="rounded border border-border-muted bg-inset px-2 py-1">
					<summary class="cursor-pointer list-none">
						<div class="flex items-start gap-2">
							<span class="shrink-0 text-[10px] font-mono text-text-muted">
								{new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
							</span>
							<span
								class="shrink-0 rounded border px-1 py-0.5 text-[10px] uppercase tracking-wide {badgeClasses(event.event_type)}"
							>
								{event.event_type}
							</span>
							<span class="min-w-0 flex-1 break-words text-[11px] text-text-secondary">
								{eventSummary(event)}
							</span>
						</div>
					</summary>
					<pre class="mt-1 overflow-x-auto rounded border border-border-muted bg-surface px-2 py-1 text-[10px] text-text-muted">{JSON.stringify(event.payload ?? {}, null, 2)}</pre>
				</details>
			{/each}
		</div>
	{/if}
</section>
