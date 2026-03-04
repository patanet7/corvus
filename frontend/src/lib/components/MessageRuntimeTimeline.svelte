<script lang="ts">
	import type { ChatRuntimeEvent } from '$lib/types';

	interface Props {
		events: ChatRuntimeEvent[];
		streaming?: boolean;
		onOpenTrace?: (callId: string) => void;
	}

	let { events, streaming = false, onOpenTrace }: Props = $props();
	let expanded = $state(false);

	const orderedEvents = $derived.by(() => [...events].sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime()));
	const previewEvent = $derived.by(() => orderedEvents.at(-1) ?? null);
	const previewLabel = $derived.by(() => {
		const event = previewEvent;
		if (!event) return '';
		if (event.kind === 'thinking' || event.kind === 'reasoning') return 'thinking';
		if (event.kind === 'todo') return 'todo update';
		if (event.kind === 'tool_start') return 'tool call';
		if (event.kind === 'tool_result') return 'tool result';
		if (event.kind === 'confirm_request') return 'approval request';
		if (event.kind === 'result') return 'result';
		return event.kind.replace(/_/g, ' ');
	});

	function rowTone(kind: ChatRuntimeEvent['kind']): string {
		if (kind === 'result') return 'border-success/30 bg-success/10 text-success';
		if (kind === 'tool_result') return 'border-info/30 bg-info/10 text-info';
		if (kind === 'confirm_request') return 'border-warning/40 bg-warning/10 text-warning';
		if (kind === 'todo') return 'border-warning/30 bg-warning/5 text-warning';
		if (kind === 'tool_start' || kind === 'phase') return 'border-border-muted bg-surface text-text-secondary';
		return 'border-border-muted bg-surface text-text-secondary';
	}
</script>

{#if orderedEvents.length > 0}
	<div class="runtime-stack rounded border border-border-muted bg-surface-raised/70 px-2 py-1.5">
		<button
			type="button"
			class="runtime-toggle flex w-full items-center gap-2 text-left"
			onclick={() => (expanded = !expanded)}
			aria-expanded={expanded}
			aria-label="Toggle assistant runtime details"
		>
			<span class="runtime-dot {streaming ? 'runtime-dot-live' : ''}"></span>
			<span class="text-[11px] text-text-muted">{previewLabel}</span>
			<span class="truncate text-[11px] text-text-secondary">{previewEvent?.summary}</span>
			<span class="ml-auto text-[10px] text-text-muted">{expanded ? 'Hide' : 'Show'}</span>
		</button>

		{#if expanded}
			<div class="mt-1.5 space-y-1 border-t border-border-muted pt-1.5">
				{#each orderedEvents as event (event.id)}
					<div class="rounded border px-2 py-1.5 text-[11px] {rowTone(event.kind)}">
						<div class="flex items-center gap-2">
							<span class="rounded border border-border-muted px-1 py-0.5 uppercase tracking-wide text-[10px]">
								{event.kind.replace(/_/g, ' ')}
							</span>
							<span class="font-mono text-[10px] text-text-muted">
								{event.timestamp.toLocaleTimeString([], {
									hour: '2-digit',
									minute: '2-digit',
									second: '2-digit'
								})}
							</span>
							{#if event.callId && onOpenTrace}
								<button
									type="button"
									class="ml-auto rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
									onclick={() => onOpenTrace(event.callId!)}
								>
									Trace
								</button>
							{/if}
						</div>
						<div class="mt-1 text-text-primary">{event.summary}</div>
						{#if event.detail && event.detail !== event.summary}
							<details class="mt-1 rounded border border-border-muted bg-inset px-1.5 py-1">
								<summary class="cursor-pointer text-[10px] text-text-muted">Details</summary>
								<pre class="mt-1 whitespace-pre-wrap break-words text-[10px] text-text-secondary">{event.detail}</pre>
							</details>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<style>
	.runtime-toggle {
		min-height: 1.5rem;
	}

	.runtime-dot {
		display: inline-flex;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 9999px;
		background: color-mix(in srgb, var(--color-text-muted) 70%, transparent);
	}

	.runtime-dot-live {
		background: var(--color-info);
		animation: runtime-pulse 1.2s ease-in-out infinite;
	}

	@keyframes runtime-pulse {
		0%,
		100% {
			opacity: 0.45;
		}
		50% {
			opacity: 1;
		}
	}
</style>
