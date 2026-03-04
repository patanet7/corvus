import { describe, it, expect } from 'vitest';
import type { ThemeConfig } from './types';
import { registerTheme, getTheme, listThemes, DEFAULT_THEME_ID } from './registry';

describe('DEFAULT_THEME_ID', () => {
	it('equals ops-cockpit', () => {
		expect(DEFAULT_THEME_ID).toBe('ops-cockpit');
	});

	it('is a string', () => {
		expect(typeof DEFAULT_THEME_ID).toBe('string');
	});

	it('corresponds to a registered theme', () => {
		const theme = getTheme(DEFAULT_THEME_ID);
		expect(theme).toBeDefined();
	});
});

describe('listThemes', () => {
	it('returns all built-in themes', () => {
		const themes = listThemes();
		expect(themes.length).toBeGreaterThanOrEqual(4);
	});

	it('returns an array', () => {
		const themes = listThemes();
		expect(Array.isArray(themes)).toBe(true);
	});

	it('every theme has an id and name', () => {
		const themes = listThemes();
		for (const theme of themes) {
			expect(theme.id).toBeTruthy();
			expect(theme.name).toBeTruthy();
		}
	});

	it('includes ops-cockpit', () => {
		const themes = listThemes();
		expect(themes.some((t) => t.id === 'ops-cockpit')).toBe(true);
	});

	it('includes retro-terminal', () => {
		const themes = listThemes();
		expect(themes.some((t) => t.id === 'retro-terminal')).toBe(true);
	});

	it('includes dark-fantasy', () => {
		const themes = listThemes();
		expect(themes.some((t) => t.id === 'dark-fantasy')).toBe(true);
	});

	it('includes tactical-rts', () => {
		const themes = listThemes();
		expect(themes.some((t) => t.id === 'tactical-rts')).toBe(true);
	});
});

describe('getTheme', () => {
	it('returns ops-cockpit theme', () => {
		const theme = getTheme('ops-cockpit');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('ops-cockpit');
		expect(theme!.name).toBe('Modern Ops Cockpit');
	});

	it('returns retro-terminal theme', () => {
		const theme = getTheme('retro-terminal');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('retro-terminal');
		expect(theme!.name).toBe('Retro Terminal');
	});

	it('returns dark-fantasy theme', () => {
		const theme = getTheme('dark-fantasy');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('dark-fantasy');
		expect(theme!.name).toBe('Dark Fantasy');
	});

	it('returns tactical-rts theme', () => {
		const theme = getTheme('tactical-rts');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('tactical-rts');
		expect(theme!.name).toBe('Tactical RTS Command');
	});

	it('returns undefined for nonexistent theme', () => {
		expect(getTheme('nonexistent')).toBeUndefined();
	});

	it('returns undefined for empty string', () => {
		expect(getTheme('')).toBeUndefined();
	});

	it('is case-sensitive', () => {
		expect(getTheme('Ops-Cockpit')).toBeUndefined();
		expect(getTheme('OPS-COCKPIT')).toBeUndefined();
	});
});

describe('registerTheme', () => {
	it('adds a new theme that can be retrieved', () => {
		const custom: ThemeConfig = createRegistryTestTheme('registry-test-1', 'Registry Test 1');
		registerTheme(custom);
		const retrieved = getTheme('registry-test-1');
		expect(retrieved).toBeDefined();
		expect(retrieved!.name).toBe('Registry Test 1');
	});

	it('newly registered theme appears in listThemes', () => {
		const custom: ThemeConfig = createRegistryTestTheme('registry-test-2', 'Registry Test 2');
		registerTheme(custom);
		const themes = listThemes();
		expect(themes.some((t) => t.id === 'registry-test-2')).toBe(true);
	});

	it('overwrites existing theme with same id', () => {
		const v1: ThemeConfig = createRegistryTestTheme('registry-overwrite', 'Version 1');
		const v2: ThemeConfig = createRegistryTestTheme('registry-overwrite', 'Version 2');
		registerTheme(v1);
		registerTheme(v2);
		expect(getTheme('registry-overwrite')!.name).toBe('Version 2');
	});

	it('does not affect other themes when registering', () => {
		const before = getTheme('ops-cockpit');
		registerTheme(createRegistryTestTheme('registry-test-3', 'Registry Test 3'));
		const after = getTheme('ops-cockpit');
		expect(before).toBe(after);
	});
});

function createRegistryTestTheme(id: string, name: string): ThemeConfig {
	return {
		id,
		name,
		colors: {
			canvas: '#000000',
			surface: '#111111',
			surfaceRaised: '#222222',
			overlay: '#333333',
			inset: '#000000',
			border: '#444444',
			borderMuted: '#333333',
			borderEmphasis: '#666666',
			textPrimary: '#ffffff',
			textSecondary: '#aaaaaa',
			textMuted: '#888888',
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
				family: 'system-ui',
				weights: [400],
				source: { type: 'system' },
				fallback: 'sans-serif',
			},
			mono: {
				family: 'monospace',
				weights: [400],
				source: { type: 'system' },
				fallback: 'monospace',
			},
		},
		atmosphere: {},
		animations: {
			easing: 'ease',
			durationScale: 1.0,
			portraitStyle: 'smooth',
		},
		portraitFrame: {
			shape: 'circle',
			border: '2px solid #444',
			background: '#111',
		},
		components: {
			statusBar: { background: '#111', separator: '|', fontFamily: 'mono' },
			modeRail: { iconWeight: 1.5, activeIndicator: 'bar' },
			chatPanel: { userMessageBg: '#222', assistantMessageBg: 'transparent', maxWidth: '900px', messagePadding: '16px' },
			toolCard: { statusBorderWidth: '2px', expandAnimation: 'slide' },
			confirmCard: { urgencyStyle: 'border', countdownStyle: 'bar' },
			codeBlock: { shikiTheme: 'github-dark', headerStyle: 'bar' },
			sidebar: { resizeHandle: 'custom-bar', activeSessionIndicator: 'left-border' },
		},
		details: {
			borderRadius: '4px',
			scrollbarWidth: 'thin',
			selectionBg: '#58a6ff33',
			selectionText: '#ffffff',
			textOnAccent: '#ffffff',
			kbdStyle: 'flat',
		},
	};
}
