<script lang="ts">
	import { clearCompletedTasks, taskStore } from '$lib/stores.svelte';
	import type { Task } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		width: number;
		onSelectTask: (taskId: string) => void;
		onInterruptTask?: (taskId: string) => void;
	}

	let { width, onSelectTask, onInterruptTask }: Props = $props();
	let filter = $state<'all' | 'active' | 'completed'>('all');

	// Derive sorted tasks: active first (by startedAt desc), then completed (by completedAt desc)
	const sortedTasks = $derived.by(() => {
		const all = Array.from(taskStore.tasks.values());
		const active = all
			.filter((t) => t.status !== 'done' && t.result === undefined)
			.sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime());
		const completed = all
			.filter((t) => t.status === 'done' || t.result !== undefined)
			.sort((a, b) => (b.completedAt?.getTime() ?? 0) - (a.completedAt?.getTime() ?? 0));
		return [...active, ...completed];
	});

	const activeCount = $derived(
		sortedTasks.filter((t) => t.status !== 'done' && t.result === undefined).length
	);

	const completedCount = $derived(
		sortedTasks.filter((t) => t.status === 'done' || t.result !== undefined).length
	);

	const visibleTasks = $derived.by(() => {
		switch (filter) {
			case 'active':
				return sortedTasks.filter((t) => t.status !== 'done' && t.result === undefined);
			case 'completed':
				return sortedTasks.filter((t) => t.status === 'done' || t.result !== undefined);
			default:
				return sortedTasks;
		}
	});

	function formatElapsed(task: Task): string {
		const end = task.completedAt ?? new Date(now);
		const ms = end.getTime() - task.startedAt.getTime();
		const seconds = Math.floor(ms / 1000);
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const remainingSec = seconds % 60;
		return `${minutes}m ${remainingSec}s`;
	}

	function formatCost(costUsd: number): string {
		return `$${costUsd.toFixed(2)}`;
	}

	function isActive(task: Task): boolean {
		return task.status !== 'done' && task.result === undefined;
	}

	function isSuccess(task: Task): boolean {
		return task.result === 'success';
	}

	function isError(task: Task): boolean {
		return task.result === 'error';
	}

	// Update elapsed times every second for active tasks
	let now = $state(Date.now());
	$effect(() => {
		if (activeCount === 0) return;
		const interval = setInterval(() => {
			now = Date.now();
		}, 1000);
		return () => clearInterval(interval);
	});
</script>

<aside
	class="flex flex-col bg-surface border-r border-border overflow-hidden"
	style="width: {width}px; min-width: 160px; max-width: 400px;"
	aria-label="Task sidebar"
>
	<!-- Header -->
	<div class="flex items-center justify-between p-3 border-b border-border-muted">
		<span class="text-sm font-medium">
			Tasks
			{#if activeCount > 0}
				<span
					class="ml-1 inline-flex items-center justify-center px-1.5 py-0.5 text-xs rounded-full bg-info text-text-primary"
				>
					{activeCount}
				</span>
			{/if}
		</span>
		{#if completedCount > 0}
			<button
				class="text-[10px] px-2 py-1 rounded border border-border text-text-secondary hover:text-text-primary hover:border-border-muted transition-colors"
				type="button"
				onclick={clearCompletedTasks}
			>
				Clear completed
			</button>
		{/if}
	</div>

	<div class="grid grid-cols-3 gap-1 px-2 py-2 border-b border-border-muted">
		<button
			class="rounded px-2 py-1 text-[10px] uppercase tracking-wide transition-colors {filter === 'all'
				? 'bg-surface-raised text-text-primary'
				: 'text-text-muted hover:text-text-primary hover:bg-surface-raised'}"
			type="button"
			onclick={() => (filter = 'all')}
		>
			All
		</button>
		<button
			class="rounded px-2 py-1 text-[10px] uppercase tracking-wide transition-colors {filter === 'active'
				? 'bg-surface-raised text-text-primary'
				: 'text-text-muted hover:text-text-primary hover:bg-surface-raised'}"
			type="button"
			onclick={() => (filter = 'active')}
		>
			Active
		</button>
		<button
			class="rounded px-2 py-1 text-[10px] uppercase tracking-wide transition-colors {filter === 'completed'
				? 'bg-surface-raised text-text-primary'
				: 'text-text-muted hover:text-text-primary hover:bg-surface-raised'}"
			type="button"
			onclick={() => (filter = 'completed')}
		>
			Completed
		</button>
	</div>

	<!-- Task list -->
	<div class="flex-1 overflow-y-auto" aria-label="Task list">
		{#if visibleTasks.length === 0}
			<div class="p-4 text-center text-text-muted text-sm">
				{#if sortedTasks.length === 0}
					No active tasks.<br />Tasks appear when agents are dispatched.
				{:else}
					No tasks in this filter.
				{/if}
			</div>
		{:else}
			{#each visibleTasks as task (task.id)}
				<div
					class="task-card w-full text-left px-3 py-2 border-b border-border-muted hover:bg-surface-raised transition-colors
						focus:outline-none focus:ring-2 focus:ring-focus
						{taskStore.activeTaskId === task.id ? 'bg-surface-raised' : ''}
						{isError(task) ? 'task-error' : ''}
						{isSuccess(task) ? 'task-success' : ''}"
					style={isActive(task) ? `border-left: 2px solid var(--color-agent-${task.agent})` : ''}
					onclick={() => onSelectTask(task.id)}
					onkeydown={(event) => {
						if (event.key === 'Enter' || event.key === ' ') {
							event.preventDefault();
							onSelectTask(task.id);
						}
					}}
					role="button"
					tabindex="0"
					aria-label="{task.agent} task: {task.description}, status: {task.status}{task.result ? `, result: ${task.result}` : ''}"
				>
					<!-- Agent row: portrait + name + result indicator -->
					<div class="flex items-center gap-2">
						<AgentPortrait agent={task.agent} status={isActive(task) ? task.status : 'idle'} size="sm" />
						<span class="text-sm text-text-primary truncate flex-1">{task.agent}</span>
						{#if isSuccess(task)}
							<span class="text-success text-sm flex-shrink-0" aria-label="Completed successfully">
								<svg
									width="14"
									height="14"
									viewBox="0 0 16 16"
									fill="currentColor"
									aria-hidden="true"
								>
									<path
										d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"
									/>
								</svg>
							</span>
						{:else if isError(task)}
							<span class="text-error text-sm flex-shrink-0" aria-label="Completed with error">
								<svg
									width="14"
									height="14"
									viewBox="0 0 16 16"
									fill="currentColor"
									aria-hidden="true"
								>
									<path
										d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"
									/>
								</svg>
							</span>
						{/if}
					</div>

					<!-- Summary text -->
					<div class="mt-1 text-xs text-text-secondary line-clamp-2">
						{task.summary || task.description}
					</div>

					<!-- Elapsed time + cost -->
					<div class="mt-1 text-xs text-text-muted font-mono tabular-nums">
						{formatElapsed(task)} &middot; {formatCost(task.costUsd)}
					</div>

					{#if isActive(task) && onInterruptTask}
						<div class="mt-1">
							<button
								class="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted hover:text-error hover:border-error transition-colors"
								type="button"
								onclick={(event) => {
									event.stopPropagation();
									onInterruptTask(task.id);
								}}
								aria-label="Interrupt task {task.id}"
							>
								Interrupt
							</button>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</aside>

<style>
	.task-card {
		transition:
			background-color var(--duration-fast) ease,
			border-color var(--duration-fast) ease;
	}

	.task-success {
		opacity: 0.7;
	}

	.task-success:hover {
		opacity: 1;
	}

	.task-error {
		background: color-mix(in srgb, var(--color-error) 5%, transparent);
	}

	.task-error:hover {
		background: color-mix(in srgb, var(--color-error) 10%, transparent);
	}
</style>
