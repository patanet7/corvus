import type { ThemeConfig } from '../types';

export const tacticalRts: ThemeConfig = {
	id: 'tactical-rts',
	name: 'Tactical RTS Command',

	colors: {
		canvas: '#0a1119',
		surface: '#111a24',
		surfaceRaised: '#172332',
		overlay: '#1f3246',
		inset: '#070d14',
		border: '#2f4559',
		borderMuted: '#203345',
		borderEmphasis: '#5fb2ea',
		textPrimary: '#d6e7f7',
		textSecondary: '#91a9c2',
		textMuted: '#688099',
		textLink: '#74d8ff',
		success: '#43d17a',
		warning: '#ffbd4a',
		error: '#ff6b63',
		info: '#59b8ff',
		focus: '#6bd4ff',
		agents: {
			personal: '#be88ff',
			work: '#68b2ff',
			homelab: '#3de2ff',
			finance: '#43dd95',
			email: '#ffca64',
			docs: '#8aa0ff',
			music: '#ff7ea1',
			home: '#ffa066',
			huginn: '#8fb5c9',
			general: '#9fc0d6'
		}
	},

	fonts: {
		sans: {
			family: 'Rajdhani',
			weights: [400, 500, 600, 700],
			source: { type: 'google', family: 'Rajdhani' },
			fallback:
				"ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
		},
		mono: {
			family: 'JetBrains Mono',
			weights: [400, 500, 700],
			source: { type: 'google', family: 'JetBrains+Mono' },
			fallback:
				"ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
		},
		display: {
			family: 'Orbitron',
			weights: [500, 700],
			source: { type: 'google', family: 'Orbitron' },
			fallback: 'ui-sans-serif, system-ui, sans-serif'
		}
	},

	atmosphere: {
		backgroundEffect:
			'radial-gradient(circle at 72% 20%, rgba(96, 206, 255, 0.08), transparent 40%), repeating-linear-gradient(0deg, rgba(96, 206, 255, 0.04), rgba(96, 206, 255, 0.04) 1px, transparent 1px, transparent 26px), repeating-linear-gradient(90deg, rgba(96, 206, 255, 0.04), rgba(96, 206, 255, 0.04) 1px, transparent 1px, transparent 26px)',
		borderStyle: 'solid',
		glowColor: '#66cbff55',
		noiseOpacity: 0.22
	},

	animations: {
		easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
		durationScale: 0.9,
		portraitStyle: 'stepped'
	},

	portraitFrame: {
		shape: 'diamond',
		border: '1px solid color-mix(in srgb, var(--color-focus) 55%, var(--color-border))',
		background: 'color-mix(in srgb, var(--color-surface-raised) 85%, black)',
		glow: '0 0 10px color-mix(in srgb, var(--color-focus) 30%, transparent)'
	},

	components: {
		statusBar: {
			background: 'color-mix(in srgb, var(--color-surface) 86%, black)',
			separator: '•',
			fontFamily: 'mono'
		},
		modeRail: {
			iconWeight: 1.75,
			activeIndicator: 'fill'
		},
		chatPanel: {
			userMessageBg: '#11253a',
			assistantMessageBg: 'transparent',
			maxWidth: '980px',
			messagePadding: '18px'
		},
		toolCard: {
			statusBorderWidth: '3px',
			expandAnimation: 'fade'
		},
		confirmCard: {
			urgencyStyle: 'glow',
			countdownStyle: 'ring'
		},
		codeBlock: {
			shikiTheme: 'vitesse-dark',
			headerStyle: 'minimal'
		},
		sidebar: {
			resizeHandle: 'hover-edge',
			activeSessionIndicator: 'glow'
		}
	},

	details: {
		borderRadius: '2px',
		scrollbarWidth: 'thin',
		selectionBg: '#66cbff33',
		selectionText: '#e9f5ff',
		textOnAccent: '#041523',
		kbdStyle: 'beveled'
	}
};
