<script lang="ts">
	import StatusChip from './primitives/StatusChip.svelte';

	type PolicyState = 'allow' | 'confirm' | 'deny';
	type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

	interface Props {
		toolId: string;
		description?: string;
		state: PolicyState;
		risk?: RiskLevel;
		trustScore?: number;
		requiresConfirm?: boolean;
		reason?: string;
	}

	let {
		toolId,
		description = '',
		state,
		risk = 'low',
		trustScore = 0,
		requiresConfirm = false,
		reason = ''
	}: Props = $props();

	const clampedTrust = $derived.by(() => Math.max(0, Math.min(100, trustScore)));

	const stateTone = $derived.by<'success' | 'warning' | 'error'>(() => {
		if (state === 'allow') return 'success';
		if (state === 'confirm') return 'warning';
		return 'error';
	});

	const riskTone = $derived.by<'neutral' | 'warning' | 'error'>(() => {
		if (risk === 'critical' || risk === 'high') return 'error';
		if (risk === 'medium') return 'warning';
		return 'neutral';
	});
</script>

<article class="rounded border border-border-muted bg-surface p-3">
	<div class="flex items-start justify-between gap-2">
		<div class="min-w-0">
			<p class="truncate text-sm font-medium text-text-primary">{toolId}</p>
			{#if description}
				<p class="mt-0.5 text-[11px] text-text-secondary">{description}</p>
			{/if}
		</div>
		<StatusChip label={state} tone={stateTone} />
	</div>

	<div class="mt-2 flex flex-wrap gap-1">
		<StatusChip label={`risk ${risk}`} tone={riskTone} />
		{#if requiresConfirm}
			<StatusChip label="confirm required" tone="warning" />
		{/if}
	</div>

	<div class="mt-3 rounded border border-border-muted bg-inset px-2 py-2">
		<div class="flex items-center justify-between text-[10px] text-text-muted">
			<span>Trust</span>
			<span>{clampedTrust}%</span>
		</div>
		<div class="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-raised">
			<div class="h-full bg-success" style={`width:${clampedTrust}%`}></div>
		</div>
	</div>

	{#if reason}
		<p class="mt-2 text-[11px] text-text-muted">{reason}</p>
	{/if}
</article>
