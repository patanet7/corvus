<script lang="ts">
	import type { RunEvent } from '$lib/api/agents';
	import StatusChip from './primitives/StatusChip.svelte';

	type ActionFilter = 'all' | 'tools' | 'confirm' | 'errors';
	type ActionTone = 'neutral' | 'success' | 'warning' | 'error' | 'info';

	interface Props {
		events: RunEvent[];
		loading?: boolean;
		error?: string | null;
	}

	interface ActionRow {
		id: string;
		eventType: string;
		tool: string | null;
		callId: string | null;
		runId: string | null;
		createdAt: string;
		summary: string;
		statusLabel: string;
		tone: ActionTone;
		payload: Record<string, unknown>;
	}

	let { events, loading = false, error = null }: Props = $props();
	let filter = $state<ActionFilter>('all');

	function asRecord(value: unknown): Record<string, unknown> {
		if (value && typeof value === 'object' && !Array.isArray(value)) {
			return value as Record<string, unknown>;
		}
		return {};
	}

	function toStringOrNull(value: unknown): string | null {
		return typeof value === 'string' && value.trim().length > 0 ? value : null;
	}

	function toActionRow(event: RunEvent): ActionRow | null {
		const payload = asRecord(event.payload);
		const callId = toStringOrNull(payload.call_id);
		const tool = toStringOrNull(payload.tool);

		if (event.event_type === 'tool_start') {
			return {
				id: `tool_start:${event.id}`,
				eventType: event.event_type,
				tool,
				callId,
				runId: event.run_id ?? null,
				createdAt: event.created_at,
				summary: `Started ${tool ?? 'tool call'}`,
				statusLabel: 'running',
				tone: 'info',
				payload
			};
		}

		if (event.event_type === 'tool_result') {
			const status = toStringOrNull(payload.status) ?? 'success';
			const output = toStringOrNull(payload.output) ?? '';
			const outputPreview = output.length > 120 ? `${output.slice(0, 120)}...` : output;
			return {
				id: `tool_result:${event.id}`,
				eventType: event.event_type,
				tool,
				callId,
				runId: event.run_id ?? null,
				createdAt: event.created_at,
				summary: outputPreview ? `Result ${status}: ${outputPreview}` : `Result ${status}`,
				statusLabel: status,
				tone: status === 'error' ? 'error' : 'success',
				payload
			};
		}

		if (event.event_type === 'confirm_request') {
			return {
				id: `confirm_request:${event.id}`,
				eventType: event.event_type,
				tool,
				callId,
				runId: event.run_id ?? null,
				createdAt: event.created_at,
				summary: `Confirmation requested for ${tool ?? 'tool call'}`,
				statusLabel: 'confirm',
				tone: 'warning',
				payload
			};
		}

		if (event.event_type === 'confirm_response') {
			const approved = payload.approved === true;
			return {
				id: `confirm_response:${event.id}`,
				eventType: event.event_type,
				tool,
				callId,
				runId: event.run_id ?? null,
				createdAt: event.created_at,
				summary: approved ? 'Confirmation approved' : 'Confirmation denied',
				statusLabel: approved ? 'approved' : 'denied',
				tone: approved ? 'success' : 'error',
				payload
			};
		}

		return null;
	}

	const actionRows = $derived.by(() =>
		events
			.map(toActionRow)
			.filter((row): row is ActionRow => row !== null)
			.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
	);

	const visibleRows = $derived.by(() => {
		if (filter === 'all') return actionRows;
		if (filter === 'tools') {
			return actionRows.filter((row) => row.eventType === 'tool_start' || row.eventType === 'tool_result');
		}
		if (filter === 'confirm') {
			return actionRows.filter(
				(row) => row.eventType === 'confirm_request' || row.eventType === 'confirm_response'
			);
		}
		return actionRows.filter((row) => row.tone === 'error');
	});
</script>

<section class="rounded border border-border-muted bg-surface px-3 py-2" aria-label="Tool action history">
	<div class="flex items-center justify-between gap-2">
		<div>
			<h4 class="text-xs uppercase tracking-wide text-text-muted">Tool Action History</h4>
			<p class="text-[11px] text-text-secondary">Tool starts, results, and confirmation actions.</p>
		</div>
		<div class="flex items-center gap-1 text-[10px]">
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'all'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'all')}
			>
				All
			</button>
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'tools'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'tools')}
			>
				Tools
			</button>
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'confirm'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'confirm')}
			>
				Confirm
			</button>
			<button
				type="button"
				class="rounded border px-1.5 py-0.5 {filter === 'errors'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-muted hover:text-text-primary'}"
				onclick={() => (filter = 'errors')}
			>
				Errors
			</button>
		</div>
	</div>

	{#if loading}
		<div class="mt-2 text-xs text-text-muted">Loading tool actions...</div>
	{:else if error}
		<div class="mt-2 rounded border border-error/40 bg-error/10 px-2 py-1 text-xs text-error">{error}</div>
	{:else if visibleRows.length === 0}
		<div class="mt-2 rounded border border-border-muted bg-inset px-2 py-2 text-xs text-text-muted">
			No tool actions captured for this run.
		</div>
	{:else}
		<div class="mt-2 max-h-[340px] space-y-1 overflow-y-auto">
			{#each visibleRows as row (row.id)}
				<details class="rounded border border-border-muted bg-inset px-2 py-1">
					<summary class="cursor-pointer list-none">
						<div class="flex items-start gap-2">
							<span class="shrink-0 font-mono text-[10px] text-text-muted">
								{new Date(row.createdAt).toLocaleTimeString([], {
									hour: '2-digit',
									minute: '2-digit',
									second: '2-digit'
								})}
							</span>
							<StatusChip label={row.statusLabel} tone={row.tone} />
							<div class="min-w-0 flex-1">
								<div class="truncate text-[11px] text-text-primary">{row.summary}</div>
								<div class="mt-0.5 flex flex-wrap gap-1 text-[10px] text-text-muted">
									{#if row.tool}
										<span class="rounded border border-border-muted px-1 py-0.5 font-mono">{row.tool}</span>
									{/if}
									{#if row.callId}
										<span class="rounded border border-border-muted px-1 py-0.5 font-mono">call {row.callId}</span>
									{/if}
									{#if row.runId}
										<span class="rounded border border-border-muted px-1 py-0.5 font-mono">run {row.runId.slice(0, 8)}</span>
									{/if}
								</div>
							</div>
						</div>
					</summary>
					<pre class="mt-1 overflow-x-auto rounded border border-border-muted bg-surface px-2 py-1 text-[10px] text-text-muted">{JSON.stringify(row.payload, null, 2)}</pre>
				</details>
			{/each}
		</div>
	{/if}
</section>
