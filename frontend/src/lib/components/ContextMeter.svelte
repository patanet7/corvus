<script lang="ts">
	interface Props {
		contextPct: number;
		tokensUsed: number;
		contextLimit: number;
		model: string;
	}

	let { contextPct, tokensUsed, contextLimit, model }: Props = $props();

	const color = $derived(
		contextPct < 50
			? 'var(--color-success)'
			: contextPct < 80
				? 'var(--color-warning)'
				: 'var(--color-error)'
	);

	const pulsing = $derived(contextPct >= 95);
</script>

<div
	class="w-full h-1 bg-border-muted relative"
	role="progressbar"
	aria-valuenow={contextPct}
	aria-valuemin={0}
	aria-valuemax={100}
	aria-label="Context window: {tokensUsed.toLocaleString()} / {contextLimit.toLocaleString()} tokens ({contextPct.toFixed(1)}%) — {model}"
	title="{tokensUsed.toLocaleString()} / {contextLimit.toLocaleString()} tokens ({contextPct.toFixed(1)}%) — {model}"
>
	<div
		class="h-full transition-all duration-500"
		class:animate-pulse={pulsing}
		style="width: {Math.min(contextPct, 100)}%; background: {color};"
	></div>
</div>
