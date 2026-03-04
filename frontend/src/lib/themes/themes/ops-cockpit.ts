import type { ThemeConfig } from '../types';

export const opsCockpit: ThemeConfig = {
	id: 'ops-cockpit',
	name: 'Modern Ops Cockpit',

	colors: {
		canvas: '#0d1117',
		surface: '#161b22',
		surfaceRaised: '#1c2128',
		overlay: '#30363d',
		inset: '#010409',
		border: '#30363d',
		borderMuted: '#21262d',
		borderEmphasis: '#8b949e',
		textPrimary: '#e6edf3',
		textSecondary: '#8b949e',
		textMuted: '#848d97',
		textLink: '#58a6ff',
		success: '#238636',
		warning: '#9e6a03',
		error: '#da3633',
		info: '#1f6feb',
		focus: '#58a6ff',
		agents: {
			personal: '#c084fc',
			work: '#60a5fa',
			homelab: '#22d3ee',
			finance: '#34d399',
			email: '#fbbf24',
				docs: '#818cf8',
				music: '#fb7185',
				home: '#f97316',
				huginn: '#64748b',
				general: '#94a3b8',
			},
	},

	fonts: {
		sans: {
			family: 'IBM Plex Sans',
			weights: [400, 500, 600, 700],
			source: { type: 'google', family: 'IBM+Plex+Sans' },
			fallback:
				"ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
		},
		mono: {
			family: 'IBM Plex Mono',
			weights: [400, 500, 700],
			source: { type: 'google', family: 'IBM+Plex+Mono' },
			fallback:
				"'Fira Code', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace",
		},
		display: {
			family: 'IBM Plex Sans Condensed',
			weights: [400, 700],
			source: { type: 'google', family: 'IBM+Plex+Sans+Condensed' },
			fallback: 'ui-sans-serif, system-ui, sans-serif',
		},
	},

	atmosphere: {
		borderStyle: 'solid',
		noiseOpacity: 0,
	},

	animations: {
		easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
		durationScale: 1.0,
		portraitStyle: 'smooth',
	},

	portraitFrame: {
		shape: 'circle',
		border: '2px solid var(--color-border)',
		background: 'var(--color-surface)',
	},

	components: {
		statusBar: {
			background: 'var(--color-surface)',
			separator: '|',
			fontFamily: 'mono',
		},
		modeRail: {
			iconWeight: 1.5,
			activeIndicator: 'bar',
		},
		chatPanel: {
			userMessageBg: '#1c2333',
			assistantMessageBg: 'transparent',
			maxWidth: '900px',
			messagePadding: '16px',
		},
		toolCard: {
			statusBorderWidth: '2px',
			expandAnimation: 'slide',
		},
		confirmCard: {
			urgencyStyle: 'border',
			countdownStyle: 'bar',
		},
		codeBlock: {
			shikiTheme: 'github-dark',
			headerStyle: 'bar',
		},
		sidebar: {
			resizeHandle: 'custom-bar',
			activeSessionIndicator: 'left-border',
		},
	},

	details: {
		borderRadius: '4px',
		scrollbarWidth: 'thin',
		selectionBg: '#58a6ff33',
		selectionText: '#e6edf3',
		textOnAccent: '#ffffff',
		kbdStyle: 'flat',
	},
};
