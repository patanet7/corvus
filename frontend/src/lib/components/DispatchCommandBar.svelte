<script lang="ts">
	import StatusChip from './primitives/StatusChip.svelte';

	interface Props {
		activeCount: number;
		paused?: boolean;
		onPauseToggle?: () => void;
		onDispatchNew?: () => void;
		onClearCompleted?: () => void;
	}

	let {
		activeCount,
		paused = false,
		onPauseToggle,
		onDispatchNew,
		onClearCompleted
	}: Props = $props();
</script>

<div class="rounded border border-border-muted bg-surface px-3 py-2">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div class="flex items-center gap-2">
			<p class="text-xs font-medium text-text-primary">Dispatch Control</p>
			<StatusChip label={`${activeCount} active`} tone={activeCount > 0 ? 'info' : 'neutral'} />
		</div>
		<div class="flex items-center gap-1">
			{#if onPauseToggle}
				<button
					type="button"
					class="rounded border border-border px-2 py-1 text-[11px] text-text-secondary transition-colors hover:text-text-primary"
					onclick={onPauseToggle}
				>
					{paused ? 'Resume' : 'Pause All'}
				</button>
			{/if}
			{#if onDispatchNew}
				<button
					type="button"
					class="rounded border border-info/50 bg-info/15 px-2 py-1 text-[11px] text-info"
					onclick={onDispatchNew}
				>
					Dispatch New
				</button>
			{/if}
			{#if onClearCompleted}
				<button
					type="button"
					class="rounded border border-border-muted px-2 py-1 text-[11px] text-text-muted"
					onclick={onClearCompleted}
				>
					Archive Done
				</button>
			{/if}
		</div>
	</div>
</div>
