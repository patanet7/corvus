<script lang="ts">
	interface Props {
		agent: string;
		model?: string | null;
		size?: 'sm' | 'md';
	}

	let { agent, model = null, size = 'sm' }: Props = $props();
</script>

<div class="identity-chip-group">
	<span
		class="identity-chip identity-chip-agent {size === 'md' ? 'identity-chip-md' : ''}"
		style="--agent-color: var(--color-agent-{agent});"
	>
		{agent}
	</span>
	{#if model}
		<span class="identity-chip identity-chip-model {size === 'md' ? 'identity-chip-md' : ''}">
			{model}
		</span>
	{/if}
</div>

<style>
	.identity-chip-group {
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
	}

	.identity-chip {
		display: inline-flex;
		align-items: center;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		padding: 0.0625rem 0.5rem;
		font-size: 0.625rem;
		line-height: 1rem;
		color: var(--color-text-muted);
		background: var(--color-surface-raised);
	}

	.identity-chip-agent {
		border-color: color-mix(in srgb, var(--agent-color) 35%, var(--color-border));
		background: color-mix(in srgb, var(--agent-color) 10%, var(--color-surface-raised));
		color: var(--color-text-secondary);
	}

	.identity-chip-model {
		opacity: 0.92;
	}

	.identity-chip-md {
		padding: 0.125rem 0.625rem;
		font-size: 0.6875rem;
	}
</style>
