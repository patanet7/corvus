<script lang="ts">
	import { getThemeContext } from '$lib/themes/context';

	type Mode = 'chat' | 'agents' | 'tasks' | 'timeline' | 'memory' | 'config';

	interface Props {
		activeMode: Mode;
		onModeChange: (mode: Mode) => void;
	}

	let { activeMode, onModeChange }: Props = $props();
	const themeCtx = getThemeContext();

	const iconStrokeWidth = $derived(themeCtx.theme.components.modeRail.iconWeight);
	const activeIndicator = $derived(themeCtx.theme.components.modeRail.activeIndicator);

	const modes: { id: Mode; label: string; enabled: boolean }[] = [
		{ id: 'chat', label: 'Chat', enabled: true },
		{ id: 'agents', label: 'Agents', enabled: true },
		{ id: 'tasks', label: 'Tasks', enabled: true },
		{ id: 'timeline', label: 'Timeline', enabled: true },
		{ id: 'memory', label: 'Memory', enabled: true },
		{ id: 'config', label: 'Config', enabled: true }
	];

	function activeModeClasses(): string {
		switch (activeIndicator) {
			case 'fill':
				return 'bg-focus text-[var(--color-text-on-accent)] border-l-2 border-l-focus';
			case 'glow':
				return 'bg-surface-raised text-text-primary border-l-2 border-l-focus mode-glow';
			case 'underline':
				return 'bg-surface-raised text-text-primary border-l-2 border-l-transparent mode-underline';
			case 'bar':
			default:
				return 'bg-surface-raised text-text-primary border-l-2 border-l-focus';
		}
	}
</script>

<nav
	class="flex flex-col items-center w-12 bg-surface border-r border-border py-2 gap-1"
	style="--mode-rail-icon-weight: {iconStrokeWidth};"
	aria-label="Mode navigation"
>
	{#each modes as mode}
		<button
			class="w-10 h-10 flex items-center justify-center rounded-lg transition-colors border-l-2
				{activeMode === mode.id
				? activeModeClasses()
				: 'text-text-muted hover:text-text-secondary hover:bg-surface-raised border-l-transparent'}
				{!mode.enabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}"
			title={mode.label}
			aria-label={mode.label}
			aria-current={activeMode === mode.id ? 'page' : undefined}
			disabled={!mode.enabled}
			onclick={() => mode.enabled && onModeChange(mode.id)}
		>
			{#if mode.id === 'chat'}
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="var(--mode-rail-icon-weight)"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
				</svg>
			{:else if mode.id === 'agents'}
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="var(--mode-rail-icon-weight)"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<circle cx="9" cy="8" r="3" />
					<circle cx="17" cy="8" r="3" />
					<path d="M2 20c0-2.8 2.7-5 6-5h2" />
					<path d="M12 20c0-2.8 2.7-5 6-5h2" />
				</svg>
			{:else if mode.id === 'tasks'}
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="var(--mode-rail-icon-weight)"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<path d="M9 11l3 3L22 4" />
					<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
				</svg>
			{:else if mode.id === 'timeline'}
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="var(--mode-rail-icon-weight)"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<line x1="18" y1="20" x2="18" y2="10" />
					<line x1="12" y1="20" x2="12" y2="4" />
					<line x1="6" y1="20" x2="6" y2="14" />
				</svg>
			{:else if mode.id === 'memory'}
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="var(--mode-rail-icon-weight)"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<ellipse cx="12" cy="5" rx="9" ry="3" />
					<path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
					<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
				</svg>
			{:else if mode.id === 'config'}
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="var(--mode-rail-icon-weight)"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<circle cx="12" cy="12" r="3" />
					<path
						d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
					/>
				</svg>
			{/if}
		</button>
	{/each}
</nav>

<style>
	.mode-glow {
		box-shadow: 0 0 10px color-mix(in srgb, var(--atmosphere-glow-color, var(--color-focus)) 40%, transparent);
	}

	.mode-underline {
		position: relative;
	}

	.mode-underline::after {
		content: '';
		position: absolute;
		left: 20%;
		right: 20%;
		bottom: 2px;
		height: 2px;
		background: var(--color-focus);
		border-radius: 999px;
	}
</style>
