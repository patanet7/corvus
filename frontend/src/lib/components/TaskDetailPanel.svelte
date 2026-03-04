<script lang="ts">
	import type { Task } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		task: Task | null;
		traceCallId?: string | null;
		onInterrupt: () => void;
		onClearTraceFocus?: () => void;
	}

	let { task, traceCallId = null, onInterrupt, onClearTraceFocus }: Props = $props();

	const isActive = $derived(task ? task.status !== 'done' && task.result === undefined : false);

	function durationLabel(taskValue: Task | null): string {
		if (!taskValue) return '--';
		const end = taskValue.completedAt ?? new Date();
		const ms = end.getTime() - taskValue.startedAt.getTime();
		const seconds = Math.floor(ms / 1000);
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const rem = seconds % 60;
		return `${minutes}m ${rem}s`;
	}

	const traceEventCount = $derived.by(() => {
		if (!task || !traceCallId) return 0;
		return (task.events ?? []).filter((event) => event.callId === traceCallId).length;
	});
</script>

<aside
	class="w-[320px] shrink-0 border-l border-border bg-surface-raised px-4 py-3 overflow-y-auto"
	aria-label="Task details"
>
	<h3 class="text-sm font-medium text-text-primary">Task Details</h3>

	{#if !task}
		<div class="mt-4 text-xs text-text-muted">Select a task to view details.</div>
	{:else}
		<div class="mt-3 flex items-center gap-2">
			<AgentPortrait agent={task.agent} status={isActive ? task.status : 'idle'} size="sm" />
			<div class="text-xs text-text-secondary">
				<div class="text-text-primary font-medium">{task.agent}</div>
				<div>{task.id}</div>
			</div>
		</div>

		<div class="mt-3 space-y-2 text-xs">
			<div>
				<div class="text-text-muted">Description</div>
				<div class="text-text-primary">{task.description}</div>
			</div>
			<div>
				<div class="text-text-muted">Summary</div>
				<div class="text-text-primary">{task.summary || 'No summary yet.'}</div>
			</div>
			<div class="grid grid-cols-2 gap-2">
				<div>
					<div class="text-text-muted">Status</div>
					<div class="text-text-primary">{task.status}</div>
				</div>
				<div>
					<div class="text-text-muted">Result</div>
					<div class="text-text-primary">{task.result ?? '--'}</div>
				</div>
				<div>
					<div class="text-text-muted">Duration</div>
					<div class="text-text-primary">{durationLabel(task)}</div>
				</div>
				<div>
					<div class="text-text-muted">Cost</div>
					<div class="text-text-primary">${task.costUsd.toFixed(2)}</div>
				</div>
			</div>
			<div>
				<div class="text-text-muted">Messages</div>
				<div class="text-text-primary">{task.messages.length}</div>
			</div>
			<div>
				<div class="text-text-muted">Event Log</div>
				{#if traceCallId}
					<div
						class="mt-1 rounded border border-info px-2 py-1 text-[11px] text-info flex items-center gap-2"
					>
						<span class="font-medium">Trace focus:</span>
						<span class="font-mono">{traceCallId}</span>
						<span class="text-text-secondary">({traceEventCount} event{traceEventCount === 1 ? '' : 's'})</span>
						{#if onClearTraceFocus}
							<button
								type="button"
								class="ml-auto rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
								onclick={onClearTraceFocus}
							>
								Clear
							</button>
						{/if}
					</div>
				{/if}
				{#if task.events && task.events.length > 0}
					<div
						class="mt-1 max-h-36 overflow-y-auto rounded border border-border-muted bg-inset px-2 py-1 space-y-1"
					>
						{#each [...task.events].slice(-8).reverse() as event}
							<div
								class="flex items-start gap-2 rounded px-1 py-0.5 text-[11px]
									{traceCallId && event.callId === traceCallId
										? 'bg-surface-raised border border-info'
										: ''}"
							>
								<span class="text-text-muted font-mono shrink-0"
									>{event.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span
								>
								<span class="text-text-secondary break-words">{event.text}</span>
								{#if event.callId}
									<span class="text-text-muted font-mono shrink-0">{event.callId}</span>
								{/if}
							</div>
						{/each}
					</div>
				{:else}
					<div class="text-text-muted">No event logs yet.</div>
				{/if}
			</div>
		</div>

		{#if isActive}
			<button
				class="mt-4 w-full rounded border px-3 py-1.5 text-xs transition-colors"
				style="border-color: var(--color-error); color: var(--color-error); background: color-mix(in srgb, var(--color-error) 12%, transparent);"
				type="button"
				onclick={onInterrupt}
			>
				Interrupt Task Agent
			</button>
		{/if}
	{/if}
</aside>
