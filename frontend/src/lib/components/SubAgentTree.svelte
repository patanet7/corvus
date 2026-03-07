<script lang="ts">
	import type { Task } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		tasks: Task[];
	}

	let { tasks }: Props = $props();

	const activeTasks = $derived(
		tasks
			.filter((t) => t.status !== 'idle')
			.sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime())
			.slice(0, 10)
	);

	const statusDot = (status: string) =>
		status === 'done'
			? 'bg-success'
			: status === 'error'
				? 'bg-error'
				: status === 'streaming' || status === 'thinking'
					? 'bg-warning'
					: 'bg-text-muted';
</script>

{#if activeTasks.length > 0}
	<section class="p-3 border-b border-border">
		<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Active Runs</h3>
		<div class="space-y-1.5">
			{#each activeTasks as task (task.id)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-1.5 h-1.5 rounded-full flex-shrink-0 {statusDot(task.status)}"></span>
					<AgentPortrait agent={task.agent} status={task.status} size="sm" />
					<span
						class="text-text-secondary truncate flex-1"
						style="color: var(--color-agent-{task.agent});"
					>
						{task.agent}
					</span>
					<span class="text-[10px] text-text-muted tabular-nums">
						{task.phase || task.status}
					</span>
					{#if task.costUsd > 0}
						<span class="text-[10px] text-text-muted tabular-nums"
							>${task.costUsd.toFixed(3)}</span
						>
					{/if}
				</div>
			{/each}
		</div>
	</section>
{/if}
