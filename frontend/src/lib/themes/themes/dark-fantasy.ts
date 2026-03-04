import type { ThemeConfig } from '../types';

export const darkFantasy: ThemeConfig = {
	id: 'dark-fantasy',
	name: 'Dark Fantasy',

	colors: {
		canvas: '#1a1510',
		surface: '#221c14',
		surfaceRaised: '#2a2318',
		overlay: '#1a1510',
		inset: '#151008',
		border: '#b8860b',
		borderMuted: '#5c430666',
		borderEmphasis: '#daa520',
		textPrimary: '#d4c5a9',
		textSecondary: '#8a7b65',
		textMuted: '#5c4d3a',
		textLink: '#daa520',
		success: '#4ade80',
		warning: '#fbbf24',
		error: '#ef4444',
		info: '#60a5fa',
		focus: '#daa520',
		agents: {
			personal: '#a855f7',
			work: '#3b82f6',
			homelab: '#06b6d4',
			finance: '#10b981',
			email: '#f59e0b',
				docs: '#6366f1',
				music: '#ec4899',
				home: '#f97316',
				huginn: '#9a8463',
				general: '#8b7355',
			},
	},

	fonts: {
		sans: {
			family: 'EB Garamond',
			weights: [400, 500, 600],
			source: { type: 'google', family: 'EB Garamond' },
			fallback: 'Georgia, serif',
		},
		mono: {
			family: 'Fira Code',
			weights: [400, 500],
			source: { type: 'google', family: 'Fira Code' },
			fallback: 'monospace',
		},
		display: {
			family: 'Cinzel Decorative',
			weights: [400, 700],
			source: { type: 'google', family: 'Cinzel Decorative' },
			fallback: 'Georgia, serif',
		},
	},

	atmosphere: {
		backgroundEffect:
			'url("data:image/svg+xml,%3Csvg viewBox=%270 0 256 256%27 xmlns=%27http://www.w3.org/2000/svg%27%3E%3Cfilter id=%27noise%27%3E%3CfeTurbulence type=%27fractalNoise%27 baseFrequency=%270.9%27 numOctaves=%274%27 stitchTiles=%27stitch%27/%3E%3C/filter%3E%3Crect width=%27100%25%27 height=%27100%25%27 filter=%27url(%23noise)%27/%3E%3C/svg%3E")',
		noiseOpacity: 0.04,
		glowColor: '#daa52033',
	},

	animations: {
		easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
		durationScale: 1.2,
		portraitStyle: 'smooth',
	},

	portraitFrame: {
		shape: 'hexagon',
		border: '2px ridge #b8860b',
		background: '#1a1510',
		glow: '0 0 8px #daa52033',
	},

	components: {
		statusBar: {
			background: '#1a1510',
			separator: '|',
			fontFamily: 'sans',
		},
		modeRail: {
			iconWeight: 1.5,
			activeIndicator: 'glow',
		},
		chatPanel: {
			userMessageBg: '#2a2015',
			assistantMessageBg: '#221c14',
			maxWidth: '780px',
			messagePadding: '1.25rem',
		},
		toolCard: {
			statusBorderWidth: '2px',
			expandAnimation: 'slide',
		},
		confirmCard: {
			urgencyStyle: 'glow',
			countdownStyle: 'ring',
		},
		codeBlock: {
			shikiTheme: 'catppuccin-mocha',
			headerStyle: 'tab',
		},
		sidebar: {
			resizeHandle: 'hover-edge',
			activeSessionIndicator: 'glow',
		},
	},

	details: {
		borderRadius: '2px',
		scrollbarWidth: 'thin',
		selectionBg: '#daa52044',
		selectionText: '#d4c5a9',
		textOnAccent: '#1a1510',
		kbdStyle: 'beveled',
	},
};
