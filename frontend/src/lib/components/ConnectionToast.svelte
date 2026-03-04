<script lang="ts">
	import type { ConnectionStatus } from '$lib/types';

	interface Props {
		status: ConnectionStatus;
		onReconnect?: () => void;
	}

	let { status, onReconnect }: Props = $props();

	const visible = $derived(status === 'error' || status === 'disconnected');

	const message = $derived(
		status === 'error'
			? 'Connection error -- retrying...'
			: status === 'disconnected'
				? 'Disconnected from server'
				: ''
	);

	const statusColor = $derived(status === 'error' ? 'var(--color-error)' : 'var(--color-warning)');
</script>

{#if visible}
	<div
		class="absolute top-2 left-1/2 -translate-x-1/2 z-10
               flex items-center gap-2 px-4 py-2 rounded-lg border text-sm
               animate-slide-down"
		style="background: color-mix(in srgb, {statusColor} 15%, var(--color-surface));
               border-color: {statusColor};"
		role="status"
	>
		<span style="color: {statusColor};">&#9679;</span>
		<span class="text-text-primary">{message}</span>
		{#if onReconnect}
			<button
				class="ml-2 rounded border border-border px-2 py-0.5 text-xs text-text-secondary hover:text-text-primary hover:border-border transition-colors"
				onclick={onReconnect}
				type="button"
				aria-label="Reconnect chat"
			>
				Reconnect
			</button>
		{/if}
	</div>
{/if}

<style>
	@keyframes slide-down {
		from {
			opacity: 0;
			transform: translate(-50%, -100%);
		}
		to {
			opacity: 1;
			transform: translate(-50%, 0);
		}
	}
	.animate-slide-down {
		animation: slide-down 200ms var(--ease-out-expo, ease-out) forwards;
	}
</style>
