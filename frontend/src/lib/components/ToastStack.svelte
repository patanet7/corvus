<script lang="ts">
	import { dismissToast, toastStore } from '$lib/chat/toasts.svelte';

	function tone(kind: string): { border: string; bg: string } {
		switch (kind) {
			case 'error':
				return {
					border: 'var(--color-error)',
					bg: 'color-mix(in srgb, var(--color-error) 12%, var(--color-surface))'
				};
			case 'warning':
				return {
					border: 'var(--color-warning)',
					bg: 'color-mix(in srgb, var(--color-warning) 12%, var(--color-surface))'
				};
			case 'success':
				return {
					border: 'var(--color-success)',
					bg: 'color-mix(in srgb, var(--color-success) 12%, var(--color-surface))'
				};
			default:
				return {
					border: 'var(--color-info)',
					bg: 'color-mix(in srgb, var(--color-info) 12%, var(--color-surface))'
				};
		}
	}
</script>

{#if toastStore.items.length > 0}
	<div class="pointer-events-none fixed right-3 top-3 z-40 flex w-[min(28rem,calc(100vw-1.5rem))] flex-col gap-2">
		{#each toastStore.items as toast (toast.id)}
			{@const ui = tone(toast.kind)}
			<div
				class="pointer-events-auto flex items-start gap-2 rounded border px-3 py-2 text-xs shadow-lg"
				style="border-color: {ui.border}; background: {ui.bg};"
				role="status"
				aria-live="polite"
			>
				<div class="flex-1 text-text-primary">{toast.message}</div>
				<button
					class="rounded border border-border-muted px-1 text-[10px] text-text-muted hover:text-text-primary"
					type="button"
					onclick={() => dismissToast(toast.id)}
					aria-label="Dismiss notification"
				>
					x
				</button>
			</div>
		{/each}
	</div>
{/if}
