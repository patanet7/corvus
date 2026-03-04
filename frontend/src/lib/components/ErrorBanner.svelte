<script lang="ts">
	interface Props {
		message: string;
		dismissible?: boolean;
		onDismiss?: () => void;
	}

	let { message, dismissible = false, onDismiss }: Props = $props();
</script>

<div
	class="flex items-start gap-2 rounded-lg border border-error p-3 text-sm"
	style="background: color-mix(in srgb, var(--color-error) 10%, var(--color-surface));"
	role="alert"
>
	<svg class="w-4 h-4 mt-0.5 flex-shrink-0 text-error" viewBox="0 0 16 16" fill="currentColor">
		<path
			d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm-.75 3.75a.75.75 0 0 1 1.5 0v4a.75.75 0 0 1-1.5 0v-4zM8 11a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"
		/>
	</svg>
	<div class="flex-1">
		<span class="font-medium text-error">Error</span>
		<p class="text-text-secondary mt-0.5">{message}</p>
	</div>
	{#if dismissible && onDismiss}
		<button
			class="text-text-muted hover:text-text-primary transition-colors"
			onclick={onDismiss}
			aria-label="Dismiss"
		>
			<svg class="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
				<path
					d="M4.28 3.22a.75.75 0 0 0-1.06 1.06L6.94 8l-3.72 3.72a.75.75 0 1 0 1.06 1.06L8 9.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L9.06 8l3.72-3.72a.75.75 0 0 0-1.06-1.06L8 6.94 4.28 3.22z"
				/>
			</svg>
		</button>
	{/if}
</div>
