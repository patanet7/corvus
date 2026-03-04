<script lang="ts">
	type StatusTone = 'neutral' | 'success' | 'warning' | 'error' | 'info' | 'agent';

	interface Props {
		label: string;
		tone?: StatusTone;
		dot?: boolean;
		uppercase?: boolean;
		className?: string;
	}

	let { label, tone = 'neutral', dot = false, uppercase = true, className = '' }: Props = $props();

	const toneClass = $derived.by(() => {
		switch (tone) {
			case 'success':
				return 'border-success/40 text-success bg-success/10';
			case 'warning':
				return 'border-warning/40 text-warning bg-warning/10';
			case 'error':
				return 'border-error/40 text-error bg-error/10';
			case 'info':
				return 'border-info/40 text-info bg-info/10';
			case 'agent':
				return 'border-focus/40 text-text-primary bg-surface-raised';
			default:
				return 'border-border-muted text-text-secondary bg-inset';
		}
	});
</script>

<span
	class={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] tracking-wide ${uppercase ? 'uppercase' : ''} ${toneClass} ${className}`}
>
	{#if dot}
		<span class="h-1.5 w-1.5 rounded-full bg-current"></span>
	{/if}
	{label}
</span>
