<script lang="ts">
	import TraceBadge from './primitives/TraceBadge.svelte';

	export interface TimelineBlock {
		id: string;
		kind: 'prompt' | 'tool' | 'output' | 'diff' | 'phase';
		title: string;
		content: string;
		meta?: string;
		timestamp?: string;
	}

	interface Props {
		blocks: TimelineBlock[];
	}

	let { blocks }: Props = $props();
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-xs uppercase tracking-wide text-text-muted">Execution Timeline</h4>
	{#if blocks.length === 0}
		<p class="mt-2 text-xs text-text-muted">No timeline blocks recorded.</p>
	{:else}
		<div class="mt-2 space-y-2">
			{#each blocks as block (block.id)}
				<div class="rounded border border-border-muted bg-inset px-2 py-2">
					<div class="flex items-center gap-2">
						{#if block.timestamp}
							<span class="font-mono text-[10px] text-text-muted">{block.timestamp}</span>
						{/if}
						<TraceBadge eventType={block.kind} />
						<span class="text-xs text-text-primary">{block.title}</span>
					</div>
					<p class="mt-1 whitespace-pre-wrap text-[11px] text-text-secondary">{block.content}</p>
					{#if block.meta}
						<p class="mt-1 text-[10px] text-text-muted">{block.meta}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</section>
