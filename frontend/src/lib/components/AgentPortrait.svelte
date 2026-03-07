<script lang="ts">
	import type { AgentStatus } from '$lib/types';
	import type { AssetDef } from '$lib/portraits/types';
	import { getPortrait } from '$lib/portraits/registry';
	import { getThemeContext } from '$lib/themes/context';
	import SvgRenderer from '$lib/portraits/renderers/SvgRenderer.svelte';
	import ImageRenderer from '$lib/portraits/renderers/ImageRenderer.svelte';
	import SpriteRenderer from '$lib/portraits/renderers/SpriteRenderer.svelte';
	import AnimatedRenderer from '$lib/portraits/renderers/AnimatedRenderer.svelte';

	type PortraitStatus = AgentStatus | 'awaiting_confirmation';

	interface Props {
		agent: string;
		status?: PortraitStatus;
		size?: 'sm' | 'md' | 'lg';
	}

	let { agent, status = 'idle', size = 'md' }: Props = $props();

	// Theme context may not be available (e.g. in tests or standalone usage)
	let themeCtx: ReturnType<typeof getThemeContext> | null = null;
	try {
		themeCtx = getThemeContext();
	} catch {
		// No ThemeProvider ancestor — use default frame styling
	}

	const sizes = { sm: 24, md: 32, lg: 48 };
	const px = $derived(sizes[size]);

	const portrait = $derived(getPortrait(agent));

	// Resolve asset for current status, falling back to idle
	const asset: AssetDef = $derived.by(() => {
		const states = portrait.states;
		if (status === 'thinking' && states.thinking) return states.thinking;
		if (status === 'streaming' && states.streaming) return states.streaming;
		if (status === 'done' && states.done) return states.done;
		if (status === 'error' && states.error) return states.error;
		return states.idle;
	});

	const statusClass = $derived(
		status === 'idle'
			? 'portrait-idle'
			: status === 'thinking'
				? 'portrait-thinking'
				: status === 'streaming'
					? 'portrait-streaming'
					: status === 'done'
						? 'portrait-done'
						: status === 'error'
							? 'portrait-error'
							: status === 'awaiting_confirmation'
								? 'portrait-awaiting-confirm'
								: ''
	);
	const motionStyle = $derived(themeCtx?.theme?.animations?.portraitStyle ?? 'smooth');
	const motionClass = $derived(motionStyle === 'stepped' ? 'motion-stepped' : 'motion-smooth');

	// Compute frame border-radius from theme portraitFrame shape
	const frameBorderRadius = $derived.by(() => {
		const shape = themeCtx?.theme?.portraitFrame?.shape ?? 'square';
		switch (shape) {
			case 'circle':
				return '50%';
			case 'square':
				return 'var(--radius-default)';
			case 'none':
				return '0';
			case 'diamond':
			case 'hexagon':
				// These use transforms/clip-path instead
				return '0';
			default:
				return 'var(--radius-default)';
		}
	});

	const frameShape = $derived(themeCtx?.theme?.portraitFrame?.shape ?? 'square');
	const frameBorder = $derived(themeCtx?.theme?.portraitFrame?.border ?? 'none');
	const frameBg = $derived(themeCtx?.theme?.portraitFrame?.background ?? 'transparent');
	const frameGlow = $derived(themeCtx?.theme?.portraitFrame?.glow ?? '');

	// Build the clip-path for hexagon shape
	const clipPath = $derived(
		frameShape === 'hexagon'
			? 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)'
			: 'none'
	);

	// Diamond uses a 45-degree rotation on the container
	const frameTransform = $derived(frameShape === 'diamond' ? 'rotate(45deg)' : 'none');
	// Counter-rotate the content inside a diamond so it stays upright
	const contentTransform = $derived(frameShape === 'diamond' ? 'rotate(-45deg)' : 'none');

	// Agent color from CSS custom property
	const agentColorVar = $derived(`var(--color-agent-${agent})`);
</script>

<div
	class="portrait-frame {statusClass} {motionClass}"
	style="
		width: {px}px;
		height: {px}px;
		--agent-color: {agentColorVar};
		--frame-radius: {frameBorderRadius};
		--frame-border: {frameBorder};
		--frame-bg: {frameBg};
		--frame-glow: {frameGlow};
		--clip-path: {clipPath};
		--frame-transform: {frameTransform};
	"
	role="img"
	aria-label="{agent} agent, status: {status}"
>
	<div class="portrait-content" style="transform: {contentTransform};">
		{#if asset.type === 'svg'}
			<SvgRenderer {asset} size={px} agentColor={agentColorVar} {status} {motionStyle} />
		{:else if asset.type === 'image'}
			<ImageRenderer {asset} size={px} agentName={agent} />
		{:else if asset.type === 'sprite'}
			<SpriteRenderer {asset} size={px} agentName={agent} />
		{:else if asset.type === 'animated'}
			<AnimatedRenderer {asset} size={px} agentName={agent} />
		{:else}
			<!-- Unsupported asset type (e.g. lottie without renderer) — fallback to empty -->
			<div style="width: {px}px; height: {px}px;" aria-hidden="true"></div>
		{/if}
	</div>
</div>

<style>
	.portrait-frame {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--frame-radius, var(--radius-default));
		border: var(--frame-border, none);
		background: var(--frame-bg, transparent);
		position: relative;
		flex-shrink: 0;
		clip-path: var(--clip-path, none);
		transform: var(--frame-transform, none);
		overflow: hidden;
	}

	.portrait-content {
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	/* ============================
	   Status Animations — 6 states
	   ============================ */

	/* 1. IDLE — gentle ambient glow breathing */
	.portrait-idle {
		animation: idle-pulse var(--duration-breathing, 4000ms) var(--ease-in-out-sine) infinite;
	}

	/* 2. THINKING — sonar rings radiating outward */
	.portrait-thinking {
		animation: thinking-sonar var(--duration-thinking, 1500ms) var(--ease-in-out-sine) infinite;
	}

	/* 3. STREAMING — rotating data-flow arc + glow */
	.portrait-streaming {
		box-shadow: 0 0 8px color-mix(in srgb, var(--agent-color) 40%, transparent);
	}

	.portrait-streaming::before {
		content: '';
		position: absolute;
		inset: -3px;
		border-radius: inherit;
		border: 2px solid transparent;
		border-top-color: var(--agent-color);
		animation: stream-arc 1.2s linear infinite;
		pointer-events: none;
	}

	.portrait-streaming::after {
		content: '';
		position: absolute;
		bottom: -2px;
		right: -2px;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--agent-color);
		animation: dot-pulse 1s var(--ease-in-out-sine) infinite;
	}

	/* 4. DONE — brief success flash + checkmark badge */
	.portrait-done {
		animation: done-flash 2s ease-out forwards;
	}

	.portrait-done::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: var(--frame-radius, var(--radius-default));
		background: color-mix(in srgb, var(--color-success) 20%, transparent);
		animation: done-fade 2s ease-out forwards;
		pointer-events: none;
	}

	/* 5. ERROR — red pulse + shake */
	.portrait-error {
		animation: error-shake 400ms ease-out;
	}

	.portrait-error::before {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: var(--frame-radius, var(--radius-default));
		background: color-mix(in srgb, var(--color-error) 30%, transparent);
		pointer-events: none;
	}

	/* 6. AWAITING CONFIRMATION — amber pulse with attention badge */
	.portrait-awaiting-confirm {
		animation: confirm-pulse 1s ease-in-out infinite;
	}

	.portrait-awaiting-confirm::after {
		content: '!';
		position: absolute;
		top: -2px;
		right: -2px;
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: var(--color-warning);
		color: var(--color-canvas);
		font-size: 8px;
		font-weight: bold;
		display: flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
		z-index: 1;
	}

	/* Stepped animation variants for retro/tactical themes */
	.motion-stepped.portrait-idle {
		animation-timing-function: steps(6, end);
	}
	.motion-stepped.portrait-thinking {
		animation-timing-function: steps(8, end);
	}
	.motion-stepped.portrait-done {
		animation-timing-function: steps(4, end);
	}
	.motion-stepped.portrait-awaiting-confirm {
		animation-timing-function: steps(4, end);
	}
	.motion-stepped.portrait-streaming::before {
		animation-timing-function: steps(12, end);
	}

	/* Glow effect from theme */
	.portrait-frame[style*='--frame-glow'] {
		box-shadow: var(--frame-glow);
	}

	/* Streaming overrides glow with its own box-shadow */
	.portrait-streaming[style*='--frame-glow'] {
		box-shadow: 0 0 8px color-mix(in srgb, var(--agent-color) 40%, transparent);
	}

	/* ============================
	   Keyframes
	   ============================ */

	@keyframes idle-pulse {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.85; transform: scale(1.02); }
	}

	@keyframes thinking-sonar {
		0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--agent-color) 30%, transparent); }
		70% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--agent-color) 0%, transparent); }
		100% { box-shadow: 0 0 0 0 transparent; }
	}

	@keyframes stream-arc {
		0% { transform: rotate(0deg); }
		100% { transform: rotate(360deg); }
	}

	@keyframes dot-pulse {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.5; transform: scale(0.7); }
	}

	@keyframes done-flash {
		0% { box-shadow: 0 0 12px color-mix(in srgb, var(--color-success) 50%, transparent); }
		100% { box-shadow: none; }
	}

	@keyframes done-fade {
		0% { opacity: 1; }
		100% { opacity: 0; }
	}

	@keyframes error-shake {
		0%, 100% { transform: translateX(0); }
		20% { transform: translateX(-2px); }
		40% { transform: translateX(2px); }
		60% { transform: translateX(-2px); }
		80% { transform: translateX(1px); }
	}

	@keyframes confirm-pulse {
		0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-warning) 40%, transparent); }
		50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-warning) 0%, transparent); }
	}

	@media (prefers-reduced-motion: reduce) {
		.portrait-idle,
		.portrait-thinking,
		.portrait-error,
		.portrait-done,
		.portrait-awaiting-confirm {
			animation: none;
		}
		.portrait-streaming::before,
		.portrait-streaming::after,
		.portrait-done::after {
			animation: none;
		}
	}
</style>
