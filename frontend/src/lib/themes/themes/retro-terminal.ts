import type { ThemeConfig } from '../types';

export const retroTerminal: ThemeConfig = {
	id: 'retro-terminal',
	name: 'Retro Terminal',

	colors: {
		canvas: '#000000',
		surface: '#0a0a0a',
		surfaceRaised: '#111111',
		overlay: '#0a0a0a',
		inset: '#050505',
		border: '#1a3a1a',
		borderMuted: '#0d1f0d',
		borderEmphasis: '#33ff33',
		textPrimary: '#33ff33',
		textSecondary: '#1a991a',
		textMuted: '#2d8a2d',
		textLink: '#66ff66',
		success: '#33ff33',
		warning: '#ffcc00',
		error: '#ff3333',
		info: '#33ccff',
		focus: '#33ff33',
		agents: {
			personal: '#cc66ff',
			work: '#66ccff',
			homelab: '#00ffcc',
			finance: '#33ff99',
			email: '#ffcc33',
				docs: '#9999ff',
				music: '#ff6699',
				home: '#ff9933',
				huginn: '#66aaaa',
				general: '#99cccc',
			},
	},

	fonts: {
		sans: {
			family: 'Share Tech Mono',
			weights: [400],
			source: { type: 'google', family: 'Share Tech Mono' },
			fallback: 'monospace',
		},
		mono: {
			family: 'VT323',
			weights: [400],
			source: { type: 'google', family: 'VT323' },
			fallback: 'monospace',
		},
		display: {
			family: 'Press Start 2P',
			weights: [400],
			source: { type: 'google', family: 'Press Start 2P' },
			fallback: 'monospace',
		},
	},

	atmosphere: {
		backgroundEffect:
			'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0, 255, 0, 0.03) 2px, rgba(0, 255, 0, 0.03) 4px)',
		noiseOpacity: 0.03,
		glowColor: '#33ff33',
	},

	animations: {
		easing: 'linear',
		durationScale: 1.0,
		portraitStyle: 'stepped',
	},

	portraitFrame: {
		shape: 'square',
		border: '1px solid #33ff33',
		background: '#0a0a0a',
	},

	components: {
		statusBar: {
			background: '#000000',
			separator: '::',
			fontFamily: 'mono',
		},
		modeRail: {
			iconWeight: 1,
			activeIndicator: 'glow',
		},
		chatPanel: {
			userMessageBg: '#0d1a0d',
			assistantMessageBg: '#0a0a0a',
			maxWidth: '800px',
			messagePadding: '1rem',
		},
		toolCard: {
			statusBorderWidth: '2px',
			expandAnimation: 'instant',
		},
		confirmCard: {
			urgencyStyle: 'border',
			countdownStyle: 'text',
		},
		codeBlock: {
			shikiTheme: 'vitesse-dark',
			headerStyle: 'bar',
		},
		sidebar: {
			resizeHandle: 'custom-bar',
			activeSessionIndicator: 'left-border',
		},
	},

	details: {
		borderRadius: '0px',
		scrollbarWidth: 'thin',
		selectionBg: '#33ff3344',
		selectionText: '#33ff33',
		textOnAccent: '#000000',
		kbdStyle: 'outline',
	},
};
