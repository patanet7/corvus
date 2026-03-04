<script lang="ts">
	import type { AssetDef } from '../types';

	interface Props {
		asset: Extract<AssetDef, { type: 'image' }>;
		size: number;
		agentName: string;
	}

	let { asset, size, agentName }: Props = $props();
</script>

<img
	src={asset.src}
	width={size}
	height={size}
	alt="{agentName} portrait"
	style="object-fit: contain;"
/>
