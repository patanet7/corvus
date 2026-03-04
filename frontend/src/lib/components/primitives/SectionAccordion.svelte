<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		subtitle?: string;
		defaultOpen?: boolean;
		badge?: string;
		children?: Snippet;
	}

	let { title, subtitle = '', defaultOpen = false, badge = '', children }: Props = $props();
</script>

<details class="rounded border border-border-muted bg-surface" open={defaultOpen}>
	<summary class="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2">
		<div>
			<p class="text-xs font-medium text-text-primary">{title}</p>
			{#if subtitle}
				<p class="text-[11px] text-text-muted">{subtitle}</p>
			{/if}
		</div>
		{#if badge}
			<span class="rounded border border-border-muted px-1.5 py-0.5 text-[10px] text-text-secondary">
				{badge}
			</span>
		{/if}
	</summary>
	<div class="border-t border-border-muted px-3 py-2">
		{@render children?.()}
	</div>
</details>
