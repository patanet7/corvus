<script lang="ts">
	import { getThemeContext } from '$lib/themes/context';

	interface Props {
		onResize: (delta: number) => void;
		direction?: 'horizontal' | 'vertical';
	}

	let { onResize, direction = 'horizontal' }: Props = $props();
	const themeCtx = getThemeContext();
	const handleStyle = $derived(themeCtx.theme.components.sidebar.resizeHandle);
	let dragging = $state(false);

	function handlePointerDown(e: PointerEvent) {
		e.preventDefault();
		dragging = true;
		const target = e.currentTarget as HTMLElement;
		target.setPointerCapture(e.pointerId);

		let lastPos = direction === 'horizontal' ? e.clientX : e.clientY;

		function handlePointerMove(ev: PointerEvent) {
			const currentPos = direction === 'horizontal' ? ev.clientX : ev.clientY;
			const delta = currentPos - lastPos;
			if (delta !== 0) {
				onResize(delta);
				lastPos = currentPos;
			}
		}

		function handlePointerUp() {
			dragging = false;
			target.removeEventListener('pointermove', handlePointerMove);
			target.removeEventListener('pointerup', handlePointerUp);
		}

		target.addEventListener('pointermove', handlePointerMove);
		target.addEventListener('pointerup', handlePointerUp);
	}
</script>

<div
	class="resize-handle {direction} style-{handleStyle} {dragging ? 'active' : ''}"
	onpointerdown={handlePointerDown}
	role="separator"
	aria-orientation={direction}
	aria-label="Resize panel"
></div>

<style>
	.resize-handle {
		flex-shrink: 0;
		z-index: 5;
		transition: background 150ms ease;
	}

	.resize-handle.horizontal {
		width: 4px;
		cursor: col-resize;
		margin: 0 -2px;
	}

	.resize-handle.vertical {
		height: 4px;
		cursor: row-resize;
		margin: -2px 0;
	}

	.resize-handle:hover,
	.resize-handle.active {
		background: var(--color-focus);
		opacity: 0.5;
	}

	.resize-handle.active {
		opacity: 0.8;
	}

	.resize-handle.style-native.horizontal {
		width: 2px;
		margin: 0;
	}

	.resize-handle.style-native.vertical {
		height: 2px;
		margin: 0;
	}

	.resize-handle.style-hover-edge.horizontal {
		width: 8px;
		margin: 0 -4px;
		background: transparent;
	}

	.resize-handle.style-hover-edge.vertical {
		height: 8px;
		margin: -4px 0;
		background: transparent;
	}

	.resize-handle:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: -2px;
	}
</style>
