<script lang="ts">
	import type { AssetDef } from '../types';

	interface Props {
		asset: Extract<AssetDef, { type: 'animated' }>;
		size: number;
		agentName: string;
	}

	let { asset, size, agentName }: Props = $props();

	let reducedMotion = $state(false);

	$effect(() => {
		if (typeof window === 'undefined') return;
		const mql = window.matchMedia('(prefers-reduced-motion: reduce)');
		reducedMotion = mql.matches;
		const handler = (e: MediaQueryListEvent) => { reducedMotion = e.matches; };
		mql.addEventListener('change', handler);
		return () => mql.removeEventListener('change', handler);
	});
</script>

{#if reducedMotion}
	<img
		src={asset.src}
		width={size}
		height={size}
		alt="{agentName} portrait"
		style="object-fit: contain;"
		loading="lazy"
	/>
{:else}
	<img
		src={asset.src}
		width={size}
		height={size}
		alt="{agentName} portrait"
		style="object-fit: contain;"
	/>
{/if}
