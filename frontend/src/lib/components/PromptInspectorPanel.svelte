<script lang="ts">
	import type { AgentPromptPreview } from '$lib/api/agents';

	interface Props {
		preview?: AgentPromptPreview | null;
		loading?: boolean;
		error?: string | null;
	}

	let { preview = null, loading = false, error = null }: Props = $props();
	let expandedLayers = $state<Record<string, boolean>>({});
	let showFullPreview = $state(false);

	function toggleLayer(layerId: string): void {
		expandedLayers[layerId] = !expandedLayers[layerId];
	}
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<div class="flex items-center justify-between gap-2">
		<div>
			<h4 class="text-sm font-medium text-text-primary">Prompt Inspector</h4>
			<p class="mt-1 text-xs text-text-secondary">
				Layered prompt preview for this agent.
			</p>
		</div>
		{#if preview}
			<span
				class="rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide {preview.safeMode
					? 'border-success/40 text-success'
					: 'border-warning/40 text-warning'}"
			>
				{preview.safeMode ? 'Safe Preview' : 'Full Preview'}
			</span>
		{/if}
	</div>

	{#if loading}
		<div class="mt-3 rounded border border-border-muted bg-inset px-2 py-2 text-[11px] text-text-muted">
			Loading prompt preview...
		</div>
	{:else if error}
		<div class="mt-3 rounded border border-error/40 bg-surface-raised px-2 py-2 text-[11px] text-error">
			{error}
		</div>
	{:else if !preview}
		<div class="mt-3 rounded border border-border-muted bg-inset px-2 py-2 text-[11px] text-text-muted">
			No prompt preview available.
		</div>
	{:else}
		<div class="mt-3 flex flex-wrap gap-1 text-[10px]">
			<span class="rounded border border-border px-1.5 py-0.5 text-text-secondary">
				{preview.totalLayers} layers
			</span>
			<span class="rounded border border-border px-1.5 py-0.5 text-text-secondary">
				{preview.totalChars} chars
			</span>
			{#if preview.fullPreviewClipped}
				<span class="rounded border border-warning/40 px-1.5 py-0.5 text-warning">clipped</span>
			{/if}
		</div>

		<div class="mt-2 rounded border border-border-muted bg-inset px-2 py-1">
			<div class="flex items-center justify-between gap-2 text-[10px] uppercase tracking-wide text-text-muted">
				<span>Composed Prompt Preview</span>
				<button
					type="button"
					class="rounded border border-border px-1.5 py-0.5 text-[10px] normal-case tracking-normal text-text-secondary hover:text-text-primary"
					onclick={() => (showFullPreview = !showFullPreview)}
				>
					{showFullPreview ? 'Collapse' : 'Expand'}
				</button>
			</div>
			{#if showFullPreview}
				<pre class="mt-2 max-h-56 overflow-auto whitespace-pre-wrap text-[11px] text-text-primary">{preview.fullPreview}</pre>
			{/if}
		</div>

		<div class="mt-2 space-y-1">
			{#each preview.layers as layer (layer.id)}
				<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px]">
					<div class="flex items-center justify-between gap-2">
						<div class="min-w-0">
							<div class="truncate font-medium text-text-primary">{layer.title}</div>
							<div class="truncate text-[10px] text-text-muted">
								{layer.source} · {layer.charCount} chars
								{#if layer.clipped}
									· clipped
								{/if}
							</div>
						</div>
						<button
							type="button"
							class="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary hover:text-text-primary"
							onclick={() => toggleLayer(layer.id)}
						>
							{expandedLayers[layer.id] ? 'Hide' : 'Show'}
						</button>
					</div>
					{#if expandedLayers[layer.id]}
						<pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-text-primary">{layer.contentPreview}</pre>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</section>
