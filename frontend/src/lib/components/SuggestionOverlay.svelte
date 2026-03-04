<script lang="ts">
	export interface SuggestionOverlayItem {
		id: string;
		label: string;
		description: string;
	}

	interface Props {
		items: SuggestionOverlayItem[];
		activeIndex: number;
		onSelect: (index: number) => void;
	}

	let { items, activeIndex, onSelect }: Props = $props();
</script>

<div class="rounded-md border border-border bg-surface-raised p-1 shadow-lg max-h-64 overflow-y-auto">
	{#each items as item, idx (item.id)}
		<button
			class="w-full rounded px-2 py-1 text-left text-xs transition-colors
				{idx === activeIndex
				? 'bg-focus text-[var(--color-text-on-accent)]'
				: 'hover:bg-surface text-text-secondary hover:text-text-primary'}"
			type="button"
			onclick={() => onSelect(idx)}
		>
			<div class="font-medium">{item.label}</div>
			<div class="text-[10px] opacity-80">{item.description}</div>
		</button>
	{/each}
</div>
