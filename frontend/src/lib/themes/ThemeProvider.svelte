<script lang="ts">
	import { setContext } from 'svelte';
	import type { ThemeConfig } from './types';
	import { getTheme, DEFAULT_THEME_ID } from './registry';
	import { THEME_KEY, type ThemeContext } from './context';

	let { children } = $props();

	const storedId =
		typeof window !== 'undefined'
			? localStorage.getItem('corvus-theme') ?? DEFAULT_THEME_ID
			: DEFAULT_THEME_ID;

	let currentThemeId = $state(storedId);

	const theme: ThemeConfig = $derived.by(() => {
		return getTheme(currentThemeId) ?? getTheme(DEFAULT_THEME_ID)!;
	});

	function setThemeId(id: string): void {
		currentThemeId = id;
		if (typeof window !== 'undefined') {
			localStorage.setItem('corvus-theme', id);
		}
	}

	const themeContext: ThemeContext = {
		get theme() {
			return theme;
		},
		setTheme: setThemeId,
	};

	setContext(THEME_KEY, themeContext);

	function buildFontUrl(t: ThemeConfig): string | null {
		const families: string[] = [];
		const fonts = [t.fonts.sans, t.fonts.mono];
		if (t.fonts.display) fonts.push(t.fonts.display);

		for (const font of fonts) {
			if (font.source.type === 'google') {
				const weights = font.weights.join(';');
				families.push(`family=${font.source.family}:wght@${weights}`);
			}
		}

		if (families.length === 0) return null;
		return `https://fonts.googleapis.com/css2?${families.join('&')}&display=swap`;
	}

	/**
	 * Inject all theme CSS custom properties on :root so they're available
	 * to body::before (atmosphere), scrollbars, ::selection, and all elements.
	 */
	$effect(() => {
		if (typeof document === 'undefined') return;
		const root = document.documentElement;
		const t = theme;

		// Colors
		root.style.setProperty('--color-canvas', t.colors.canvas);
		root.style.setProperty('--color-surface', t.colors.surface);
		root.style.setProperty('--color-surface-raised', t.colors.surfaceRaised);
		root.style.setProperty('--color-overlay', t.colors.overlay);
		root.style.setProperty('--color-inset', t.colors.inset);
		root.style.setProperty('--color-border', t.colors.border);
		root.style.setProperty('--color-border-muted', t.colors.borderMuted);
		root.style.setProperty('--color-border-emphasis', t.colors.borderEmphasis);
		root.style.setProperty('--color-text-primary', t.colors.textPrimary);
		root.style.setProperty('--color-text-secondary', t.colors.textSecondary);
		root.style.setProperty('--color-text-muted', t.colors.textMuted);
		root.style.setProperty('--color-text-link', t.colors.textLink);
		root.style.setProperty('--color-success', t.colors.success);
		root.style.setProperty('--color-warning', t.colors.warning);
		root.style.setProperty('--color-error', t.colors.error);
		root.style.setProperty('--color-info', t.colors.info);
		root.style.setProperty('--color-focus', t.colors.focus);
		root.style.setProperty('--color-user-message-bg', t.components.chatPanel.userMessageBg);

		// Agent colors — iterate keys from theme config (not hardcoded list)
		for (const [name, color] of Object.entries(t.colors.agents)) {
			root.style.setProperty(`--color-agent-${name}`, color);
		}

		// Fonts
		const displayFont = t.fonts.display ?? t.fonts.sans;
		root.style.setProperty('--font-sans', `'${t.fonts.sans.family}', ${t.fonts.sans.fallback}`);
		root.style.setProperty('--font-mono', `'${t.fonts.mono.family}', ${t.fonts.mono.fallback}`);
		root.style.setProperty('--font-display', `'${displayFont.family}', ${displayFont.fallback}`);

		// Details
		root.style.setProperty('--radius-default', t.details.borderRadius);
		root.style.setProperty('--radius-sm', `calc(${t.details.borderRadius} * 0.5)`);
		root.style.setProperty('--radius-md', `calc(${t.details.borderRadius} * 1.5)`);
		root.style.setProperty('--radius-lg', `calc(${t.details.borderRadius} * 2)`);
		root.style.setProperty('--scrollbar-width', t.details.scrollbarWidth);
		root.style.setProperty('--color-selection-bg', t.details.selectionBg);
		root.style.setProperty('--color-selection-text', t.details.selectionText);
		root.style.setProperty('--color-text-on-accent', t.details.textOnAccent);

		// Animations
		root.style.setProperty('--theme-easing', t.animations.easing);
		root.style.setProperty('--theme-duration-scale', String(t.animations.durationScale));
		root.style.setProperty('--theme-portrait-style', t.animations.portraitStyle);

		// Component-level behavior tokens
		root.style.setProperty('--theme-statusbar-bg', t.components.statusBar.background);
		root.style.setProperty('--theme-statusbar-font-family', t.components.statusBar.fontFamily);
		root.style.setProperty('--theme-mode-rail-icon-weight', String(t.components.modeRail.iconWeight));
		root.style.setProperty('--theme-mode-rail-active-indicator', t.components.modeRail.activeIndicator);
		root.style.setProperty('--theme-chat-max-width', t.components.chatPanel.maxWidth);
		root.style.setProperty('--theme-chat-message-padding', t.components.chatPanel.messagePadding);
		root.style.setProperty('--theme-toolcard-status-border-width', t.components.toolCard.statusBorderWidth);
		root.style.setProperty('--theme-toolcard-expand-animation', t.components.toolCard.expandAnimation);
		root.style.setProperty('--theme-confirm-urgency-style', t.components.confirmCard.urgencyStyle);
		root.style.setProperty('--theme-confirm-countdown-style', t.components.confirmCard.countdownStyle);
		root.style.setProperty('--theme-sidebar-resize-handle', t.components.sidebar.resizeHandle);
		root.style.setProperty(
			'--theme-sidebar-active-session-indicator',
			t.components.sidebar.activeSessionIndicator
		);
		root.style.setProperty('--theme-surface-texture', t.atmosphere.surfaceTexture ?? 'none');
		root.style.setProperty('--theme-border-style', t.atmosphere.borderStyle ?? 'solid');
		root.style.setProperty('--theme-status-separator', t.components.statusBar.separator);

		// Data attributes are used by CSS selectors for style variants.
		root.dataset.themeId = t.id;
		root.dataset.kbdStyle = t.details.kbdStyle;
		root.dataset.modeRailIndicator = t.components.modeRail.activeIndicator;
		root.dataset.toolExpand = t.components.toolCard.expandAnimation;
		root.dataset.confirmUrgency = t.components.confirmCard.urgencyStyle;
		root.dataset.confirmCountdown = t.components.confirmCard.countdownStyle;

		// Atmosphere
		if (t.atmosphere.glowColor) {
			root.style.setProperty('--atmosphere-glow-color', t.atmosphere.glowColor);
		} else {
			root.style.removeProperty('--atmosphere-glow-color');
		}
	});

	const fontUrl: string | null = $derived(buildFontUrl(theme));
</script>

<svelte:head>
	<meta name="theme-color" content={theme.colors.canvas} />
	{#if fontUrl}
		<link rel="preconnect" href="https://fonts.googleapis.com" />
		<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
		<link rel="stylesheet" href={fontUrl} />
	{/if}
</svelte:head>

{@render children()}

{#if theme.atmosphere.backgroundEffect}
	<div
		class="fixed inset-0 pointer-events-none z-[1]"
		style="background: {theme.atmosphere.backgroundEffect}; opacity: {theme.atmosphere.noiseOpacity ?? 0.03};"
		aria-hidden="true"
	></div>
{/if}
