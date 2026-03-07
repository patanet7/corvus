<script lang="ts">
	import type { AssetDef } from '../types';
	import type { AgentStatus } from '$lib/types';

	interface Props {
		asset: Extract<AssetDef, { type: 'svg' }>;
		size: number;
		agentColor: string;
		status?: string;
		motionStyle?: 'smooth' | 'stepped';
	}

	let { asset, size, agentColor, status = 'idle', motionStyle = 'smooth' }: Props = $props();
</script>

<svg
	viewBox={asset.viewBox}
	width={size}
	height={size}
	xmlns="http://www.w3.org/2000/svg"
	aria-hidden="true"
	style="color: {agentColor};"
	class="portrait-svg status-{status} motion-{motionStyle}"
>
	{#each asset.paths as path, idx}
		<path
			d={path.d}
			fill={path.fill ?? 'currentColor'}
			stroke={path.stroke}
			stroke-width={path.strokeWidth}
			opacity={path.opacity}
			class={idx === asset.paths.length - 1 ? 'layer-glyph' : idx === 0 ? 'layer-bg' : 'layer-outline'}
		/>
	{/each}
</svg>

<style>
	.portrait-svg {
		overflow: visible;
	}

	.portrait-svg.status-thinking .layer-glyph {
		transform-origin: center;
		animation: glyph-breathe 1.35s var(--ease-in-out-sine, ease-in-out) infinite;
	}

	.portrait-svg.status-streaming .layer-glyph {
		transform-origin: center;
		animation: glyph-shift 0.7s var(--ease-in-out-sine, ease-in-out) infinite;
	}

	.portrait-svg.status-done .layer-glyph {
		animation: glyph-done 300ms ease-out 1;
	}

	.portrait-svg.status-error .layer-glyph {
		animation: glyph-error 420ms ease-out 1;
	}

	.portrait-svg.motion-stepped.status-thinking .layer-glyph {
		animation-timing-function: steps(4, end);
	}

	.portrait-svg.motion-stepped.status-streaming .layer-glyph {
		animation-timing-function: steps(5, end);
	}

	@keyframes glyph-breathe {
		0%,
		100% {
			opacity: 0.8;
			transform: scale(1);
		}
		50% {
			opacity: 1;
			transform: scale(1.045);
		}
	}

	@keyframes glyph-shift {
		0% {
			transform: translateX(0) translateY(0);
		}
		33% {
			transform: translateX(0.8px) translateY(-0.5px);
		}
		66% {
			transform: translateX(-0.8px) translateY(0.5px);
		}
		100% {
			transform: translateX(0) translateY(0);
		}
	}

	@keyframes glyph-done {
		0% {
			opacity: 0.65;
			transform: scale(0.92);
		}
		100% {
			opacity: 0.9;
			transform: scale(1);
		}
	}

	@keyframes glyph-error {
		0%,
		100% {
			transform: translateX(0);
			opacity: 0.9;
		}
		25% {
			transform: translateX(-0.7px);
		}
		50% {
			transform: translateX(0.7px);
		}
		75% {
			transform: translateX(-0.4px);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.portrait-svg .layer-glyph {
			animation: none !important;
			transform: none !important;
		}
	}
</style>
