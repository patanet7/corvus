<script lang="ts">
	import type { AgentStatus, Task } from '$lib/types';

	interface Props {
		agentStatus: AgentStatus;
		runtimeTask: Task | null;
		onOpenTrace?: (callId: string) => void;
	}

	let { agentStatus, runtimeTask, onOpenTrace }: Props = $props();
	let expanded = $state(false);

	const isActive = $derived.by(() => {
		if (agentStatus === 'thinking' || agentStatus === 'streaming') return true;
		if (!runtimeTask) return false;
		return runtimeTask.status !== 'done' || runtimeTask.result === undefined;
	});

	const statusLabel = $derived.by(() => {
		if (agentStatus === 'thinking') return 'Thinking';
		if (agentStatus === 'streaming') return 'Streaming';
		if (agentStatus === 'error') return 'Error';
		if (agentStatus === 'done') return 'Done';
		return 'Idle';
	});

	const statusTone = $derived.by(() => {
		if (agentStatus === 'thinking' || agentStatus === 'streaming') {
			return 'border-info text-info';
		}
		if (agentStatus === 'error') return 'border-error text-error';
		if (agentStatus === 'done') return 'border-success text-success';
		return 'border-border-muted text-text-muted';
	});

	const phaseLabel = $derived.by(() => {
		if (runtimeTask?.phase) return runtimeTask.phase;
		if (agentStatus === 'thinking') return 'planning';
		if (agentStatus === 'streaming') return 'executing';
		if (agentStatus === 'done') return 'done';
		if (agentStatus === 'error') return 'error';
		return 'idle';
	});

	const recentEvents = $derived.by(() => {
		if (!runtimeTask?.events || runtimeTask.events.length === 0) return [];
		return [...runtimeTask.events].slice(-10).reverse();
	});
</script>

{#if isActive || expanded}
	<div class="rounded border border-border-muted bg-surface-raised px-3 py-2 text-xs">
		<button
			type="button"
			class="flex w-full items-center gap-2 text-left"
			onclick={() => (expanded = !expanded)}
			aria-expanded={expanded}
			aria-label="Toggle runtime details"
		>
			<span class="inline-flex h-2 w-2 rounded-full bg-info motion-safe:animate-pulse"></span>
			<span class="font-medium text-text-primary">{statusLabel}</span>
			<span class="rounded border px-1.5 py-0.5 text-[10px] uppercase {statusTone}">
				{phaseLabel}
			</span>
			<span class="ml-auto text-[11px] text-text-secondary">
				{expanded ? 'Hide details' : 'Show details'}
			</span>
		</button>

		{#if expanded}
			<div class="mt-2 space-y-1 border-t border-border-muted pt-2">
				{#if recentEvents.length === 0}
					<div class="text-[11px] text-text-muted">No runtime events yet.</div>
				{:else}
					{#each recentEvents as event}
						<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
							<div class="flex items-center gap-2">
								<span class="font-mono text-text-muted">
									{event.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
								</span>
								<span class="text-text-secondary uppercase">{event.kind}</span>
								{#if event.callId && onOpenTrace}
									<button
										type="button"
										class="ml-auto rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
										onclick={() => onOpenTrace(event.callId!)}
									>
										Open trace
									</button>
								{/if}
							</div>
							<div class="mt-0.5 text-text-primary break-words">{event.text}</div>
						</div>
					{/each}
				{/if}
			</div>
		{/if}
	</div>
{/if}
