<script lang="ts">
	import type { ModelInfo } from '$lib/types';

	interface Props {
		selectedModel: string;
		models: ModelInfo[];
		contextPct: number;
	}

	let { selectedModel, models, contextPct }: Props = $props();

	const selected = $derived(
		models.find((model) => model.id === selectedModel) ??
			models.find((model) => model.isDefault) ??
			models[0]
	);

	const contextState = $derived.by(() => {
		if (contextPct >= 98) return { label: 'Context Full', className: 'text-error border-error' };
		if (contextPct >= 90)
			return { label: 'Context Critical', className: 'text-error border-error' };
		if (contextPct >= 75)
			return { label: 'Context High', className: 'text-warning border-warning' };
		return { label: 'Context Stable', className: 'text-success border-success' };
	});
</script>

{#if selected}
	<div class="flex flex-wrap items-center gap-1.5 text-[10px]">
		<span
			class="rounded border border-border px-1.5 py-0.5 font-medium text-text-primary"
			title={selected.id}
		>
			{selected.label}
		</span>
		<span class="rounded border border-border-muted px-1.5 py-0.5 text-text-secondary">
			{selected.backend}
		</span>
		<span
			class="rounded border px-1.5 py-0.5 {selected.available
				? 'border-success text-success'
				: 'border-error text-error'}"
		>
			{selected.available ? 'online' : 'offline'}
		</span>
		<span
			class="rounded border px-1.5 py-0.5 {selected.capabilities?.supports_tools
				? 'border-success text-success'
				: 'border-warning text-warning'}"
		>
			{selected.capabilities?.supports_tools ? 'tools' : 'chat-only'}
		</span>
		<span
			class="rounded border px-1.5 py-0.5 {selected.capabilities?.supports_streaming
				? 'border-success text-success'
				: 'border-warning text-warning'}"
		>
			{selected.capabilities?.supports_streaming ? 'streaming' : 'non-streaming'}
		</span>
		<span class="rounded border px-1.5 py-0.5 {contextState.className}">
			{contextState.label} ({contextPct.toFixed(0)}%)
		</span>
	</div>
{/if}
