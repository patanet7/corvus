<script lang="ts">
	import type { AssetDef } from '../types';

	interface Props {
		asset: Extract<AssetDef, { type: 'sprite' }>;
		size: number;
		agentName: string;
	}

	let { asset, size, agentName }: Props = $props();

	const scale = $derived(size / asset.frameHeight);
	const displayWidth = $derived(asset.frameWidth * scale);
	const displayHeight = $derived(asset.frameHeight * scale);
	const totalWidth = $derived(displayWidth * asset.frameCount);
	const duration = $derived(asset.frameCount / asset.fps);
</script>

<div
	class="sprite"
	role="img"
	aria-label="{agentName} portrait"
	style="
		width: {displayWidth}px;
		height: {displayHeight}px;
		background: url({asset.src}) no-repeat;
		background-size: {totalWidth}px {displayHeight}px;
		animation: sprite-play {duration}s steps({asset.frameCount}) infinite;
	"
></div>

<style>
	@keyframes sprite-play {
		to {
			background-position: -100% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.sprite {
			animation: none !important;
		}
	}
</style>
