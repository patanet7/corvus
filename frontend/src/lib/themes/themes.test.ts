import { describe, it, expect } from 'vitest';
import type { ThemeConfig, FontDef } from './types';
import { WELL_KNOWN_AGENTS } from '$lib/types';
import { opsCockpit } from './themes/ops-cockpit';
import { retroTerminal } from './themes/retro-terminal';
import { darkFantasy } from './themes/dark-fantasy';
import { tacticalRts } from './themes/tactical-rts';
import { registerTheme, getTheme, listThemes, DEFAULT_THEME_ID } from './registry';

describe('ThemeConfig type definitions', () => {
	it('FontDef accepts google source', () => {
		const font: FontDef = {
			family: 'IBM Plex Sans',
			weights: [400, 500, 600, 700],
			source: { type: 'google', family: 'IBM+Plex+Sans' },
			fallback: 'ui-sans-serif, system-ui, sans-serif',
		};
		expect(font.family).toBe('IBM Plex Sans');
		expect(font.weights).toEqual([400, 500, 600, 700]);
		expect(font.source.type).toBe('google');
		expect(font.fallback).toContain('sans-serif');
	});

	it('FontDef accepts local source', () => {
		const font: FontDef = {
			family: 'CustomFont',
			weights: [400, 700],
			source: { type: 'local', files: { 400: '/fonts/custom-400.woff2', 700: '/fonts/custom-700.woff2' } },
			fallback: 'serif',
		};
		expect(font.source.type).toBe('local');
		if (font.source.type === 'local') {
			expect(font.source.files[400]).toBe('/fonts/custom-400.woff2');
		}
	});

	it('FontDef accepts system source', () => {
		const font: FontDef = {
			family: 'system-ui',
			weights: [400],
			source: { type: 'system' },
			fallback: 'sans-serif',
		};
		expect(font.source.type).toBe('system');
	});

	it('ThemeConfig has all required sections', () => {
		const theme: ThemeConfig = createMinimalTheme();
		expect(theme.id).toBe('test-theme');
		expect(theme.name).toBe('Test Theme');
		expect(theme.colors).toBeDefined();
		expect(theme.fonts).toBeDefined();
		expect(theme.atmosphere).toBeDefined();
		expect(theme.animations).toBeDefined();
		expect(theme.portraitFrame).toBeDefined();
		expect(theme.components).toBeDefined();
		expect(theme.details).toBeDefined();
	});

	it('ThemeConfig colors.agents covers all AgentName values', () => {
		const theme = createMinimalTheme();
		for (const name of WELL_KNOWN_AGENTS) {
			expect(theme.colors.agents[name]).toBeDefined();
			expect(typeof theme.colors.agents[name]).toBe('string');
		}
	});

	it('ThemeConfig fonts.display is optional', () => {
		const theme = createMinimalTheme();
		// display is not set — should be undefined
		expect(theme.fonts.display).toBeUndefined();

		// Now set it
		const themeWithDisplay: ThemeConfig = {
			...theme,
			fonts: {
				...theme.fonts,
				display: {
					family: 'IBM Plex Sans Condensed',
					weights: [400, 700],
					source: { type: 'google', family: 'IBM+Plex+Sans+Condensed' },
					fallback: 'sans-serif',
				},
			},
		};
		expect(themeWithDisplay.fonts.display).toBeDefined();
		expect(themeWithDisplay.fonts.display!.family).toBe('IBM Plex Sans Condensed');
	});

	it('ThemeConfig atmosphere fields are optional', () => {
		const theme = createMinimalTheme();
		expect(theme.atmosphere.backgroundEffect).toBeUndefined();
		expect(theme.atmosphere.surfaceTexture).toBeUndefined();
		expect(theme.atmosphere.borderStyle).toBeUndefined();
		expect(theme.atmosphere.glowColor).toBeUndefined();
		expect(theme.atmosphere.noiseOpacity).toBeUndefined();
	});

	it('ThemeConfig portraitFrame.glow is optional', () => {
		const theme = createMinimalTheme();
		expect(theme.portraitFrame.glow).toBeUndefined();
	});

	it('ThemeConfig animations validates portrait style values', () => {
		const smooth: ThemeConfig = { ...createMinimalTheme(), animations: { easing: 'ease', durationScale: 1.0, portraitStyle: 'smooth' } };
		const stepped: ThemeConfig = { ...createMinimalTheme(), animations: { easing: 'ease', durationScale: 1.0, portraitStyle: 'stepped' } };
		expect(smooth.animations.portraitStyle).toBe('smooth');
		expect(stepped.animations.portraitStyle).toBe('stepped');
	});

	it('ThemeConfig components has all sub-sections', () => {
		const theme = createMinimalTheme();
		expect(theme.components.statusBar).toBeDefined();
		expect(theme.components.modeRail).toBeDefined();
		expect(theme.components.chatPanel).toBeDefined();
		expect(theme.components.toolCard).toBeDefined();
		expect(theme.components.confirmCard).toBeDefined();
		expect(theme.components.codeBlock).toBeDefined();
		expect(theme.components.sidebar).toBeDefined();
	});
});

describe('Ops Cockpit theme', () => {
	it('has correct identity', () => {
		expect(opsCockpit.id).toBe('ops-cockpit');
		expect(opsCockpit.name).toBe('Modern Ops Cockpit');
	});

	it('colors match app.css values exactly', () => {
		expect(opsCockpit.colors.canvas).toBe('#0d1117');
		expect(opsCockpit.colors.surface).toBe('#161b22');
		expect(opsCockpit.colors.surfaceRaised).toBe('#1c2128');
		expect(opsCockpit.colors.overlay).toBe('#30363d');
		expect(opsCockpit.colors.inset).toBe('#010409');
		expect(opsCockpit.colors.border).toBe('#30363d');
		expect(opsCockpit.colors.borderMuted).toBe('#21262d');
		expect(opsCockpit.colors.borderEmphasis).toBe('#8b949e');
		expect(opsCockpit.colors.textPrimary).toBe('#e6edf3');
		expect(opsCockpit.colors.textSecondary).toBe('#8b949e');
		expect(opsCockpit.colors.textMuted).toBe('#848d97');
		expect(opsCockpit.colors.textLink).toBe('#58a6ff');
		expect(opsCockpit.colors.success).toBe('#238636');
		expect(opsCockpit.colors.warning).toBe('#9e6a03');
		expect(opsCockpit.colors.error).toBe('#da3633');
		expect(opsCockpit.colors.info).toBe('#1f6feb');
		expect(opsCockpit.colors.focus).toBe('#58a6ff');
	});

	it('agent colors match app.css values exactly', () => {
		expect(opsCockpit.colors.agents.personal).toBe('#c084fc');
		expect(opsCockpit.colors.agents.work).toBe('#60a5fa');
		expect(opsCockpit.colors.agents.homelab).toBe('#22d3ee');
		expect(opsCockpit.colors.agents.finance).toBe('#34d399');
		expect(opsCockpit.colors.agents.email).toBe('#fbbf24');
			expect(opsCockpit.colors.agents.docs).toBe('#818cf8');
			expect(opsCockpit.colors.agents.music).toBe('#fb7185');
			expect(opsCockpit.colors.agents.home).toBe('#f97316');
			expect(opsCockpit.colors.agents.huginn).toBe('#64748b');
			expect(opsCockpit.colors.agents.general).toBe('#94a3b8');
		});

	it('covers all agent names', () => {
		for (const name of WELL_KNOWN_AGENTS) {
			expect(opsCockpit.colors.agents[name]).toBeDefined();
		}
	});

	it('uses IBM Plex font family', () => {
		expect(opsCockpit.fonts.sans.family).toBe('IBM Plex Sans');
		expect(opsCockpit.fonts.mono.family).toBe('IBM Plex Mono');
		expect(opsCockpit.fonts.display?.family).toBe('IBM Plex Sans Condensed');
	});

	it('fonts use Google source', () => {
		expect(opsCockpit.fonts.sans.source.type).toBe('google');
		expect(opsCockpit.fonts.mono.source.type).toBe('google');
		expect(opsCockpit.fonts.display?.source.type).toBe('google');
	});

	it('has correct animation settings', () => {
		expect(opsCockpit.animations.easing).toBe('cubic-bezier(0.16, 1, 0.3, 1)');
		expect(opsCockpit.animations.durationScale).toBe(1.0);
		expect(opsCockpit.animations.portraitStyle).toBe('smooth');
	});

	it('portrait frame is circle', () => {
		expect(opsCockpit.portraitFrame.shape).toBe('circle');
	});

	it('code block uses github-dark Shiki theme', () => {
		expect(opsCockpit.components.codeBlock.shikiTheme).toBe('github-dark');
	});

	it('details match design spec', () => {
		expect(opsCockpit.details.borderRadius).toBe('4px');
		expect(opsCockpit.details.scrollbarWidth).toBe('thin');
		expect(opsCockpit.details.kbdStyle).toBe('flat');
	});

	it('user message background matches app.css', () => {
		expect(opsCockpit.components.chatPanel.userMessageBg).toBe('#1c2333');
	});
});

describe('Retro Terminal theme', () => {
	it('has correct identity', () => {
		expect(retroTerminal.id).toBe('retro-terminal');
		expect(retroTerminal.name).toBe('Retro Terminal');
	});

	it('uses VT323 mono font', () => {
		expect(retroTerminal.fonts.mono.family).toBe('VT323');
	});

	it('uses Share Tech Mono sans font', () => {
		expect(retroTerminal.fonts.sans.family).toBe('Share Tech Mono');
	});

	it('uses Press Start 2P display font', () => {
		expect(retroTerminal.fonts.display?.family).toBe('Press Start 2P');
	});

	it('fonts use Google source', () => {
		expect(retroTerminal.fonts.sans.source.type).toBe('google');
		expect(retroTerminal.fonts.mono.source.type).toBe('google');
		expect(retroTerminal.fonts.display?.source.type).toBe('google');
	});

	it('has CRT scanline atmosphere', () => {
		expect(retroTerminal.atmosphere.backgroundEffect).toBeDefined();
		expect(retroTerminal.atmosphere.backgroundEffect).toContain('repeating-linear-gradient');
	});

	it('has phosphor green glow color', () => {
		expect(retroTerminal.atmosphere.glowColor).toBe('#33ff33');
	});

	it('has square portrait frame', () => {
		expect(retroTerminal.portraitFrame.shape).toBe('square');
	});

	it('has 0px border radius', () => {
		expect(retroTerminal.details.borderRadius).toBe('0px');
	});

	it('has all 10 agent colors', () => {
		expect(Object.keys(retroTerminal.colors.agents)).toHaveLength(10);
	});

	it('covers all agent names', () => {
		for (const name of WELL_KNOWN_AGENTS) {
			expect(retroTerminal.colors.agents[name]).toBeDefined();
		}
	});

	it('uses neon agent colors', () => {
		expect(retroTerminal.colors.agents.personal).toBe('#cc66ff');
		expect(retroTerminal.colors.agents.work).toBe('#66ccff');
		expect(retroTerminal.colors.agents.homelab).toBe('#00ffcc');
		expect(retroTerminal.colors.agents.finance).toBe('#33ff99');
		expect(retroTerminal.colors.agents.email).toBe('#ffcc33');
			expect(retroTerminal.colors.agents.docs).toBe('#9999ff');
			expect(retroTerminal.colors.agents.music).toBe('#ff6699');
			expect(retroTerminal.colors.agents.home).toBe('#ff9933');
			expect(retroTerminal.colors.agents.huginn).toBe('#66aaaa');
			expect(retroTerminal.colors.agents.general).toBe('#99cccc');
		});

	it('colors use phosphor green primary text', () => {
		expect(retroTerminal.colors.textPrimary).toBe('#33ff33');
	});

	it('has pure black canvas', () => {
		expect(retroTerminal.colors.canvas).toBe('#000000');
	});

	it('has stepped portrait animation style', () => {
		expect(retroTerminal.animations.portraitStyle).toBe('stepped');
	});

	it('has linear animation easing', () => {
		expect(retroTerminal.animations.easing).toBe('linear');
	});

	it('code block uses vitesse-dark Shiki theme', () => {
		expect(retroTerminal.components.codeBlock.shikiTheme).toBe('vitesse-dark');
	});

	it('tool card uses instant expand animation', () => {
		expect(retroTerminal.components.toolCard.expandAnimation).toBe('instant');
	});

	it('mode rail uses glow active indicator', () => {
		expect(retroTerminal.components.modeRail.activeIndicator).toBe('glow');
	});

	it('details match design spec', () => {
		expect(retroTerminal.details.scrollbarWidth).toBe('thin');
		expect(retroTerminal.details.selectionBg).toBe('#33ff3344');
		expect(retroTerminal.details.selectionText).toBe('#33ff33');
		expect(retroTerminal.details.textOnAccent).toBe('#000000');
		expect(retroTerminal.details.kbdStyle).toBe('outline');
	});

	it('user message background is dark green', () => {
		expect(retroTerminal.components.chatPanel.userMessageBg).toBe('#0d1a0d');
	});
});

describe('Dark Fantasy theme', () => {
	it('has correct identity', () => {
		expect(darkFantasy.id).toBe('dark-fantasy');
		expect(darkFantasy.name).toBe('Dark Fantasy');
	});

	it('uses EB Garamond serif font', () => {
		expect(darkFantasy.fonts.sans.family).toBe('EB Garamond');
	});

	it('uses Fira Code mono font', () => {
		expect(darkFantasy.fonts.mono.family).toBe('Fira Code');
	});

	it('uses Cinzel Decorative display font', () => {
		expect(darkFantasy.fonts.display?.family).toBe('Cinzel Decorative');
	});

	it('fonts use Google source', () => {
		expect(darkFantasy.fonts.sans.source.type).toBe('google');
		expect(darkFantasy.fonts.mono.source.type).toBe('google');
		expect(darkFantasy.fonts.display?.source.type).toBe('google');
	});

	it('has parchment noise atmosphere', () => {
		expect(darkFantasy.atmosphere.backgroundEffect).toBeDefined();
		expect(darkFantasy.atmosphere.backgroundEffect).toContain('feTurbulence');
	});

	it('has warm candlelight glow color', () => {
		expect(darkFantasy.atmosphere.glowColor).toBe('#daa52033');
	});

	it('has noise opacity of 0.04', () => {
		expect(darkFantasy.atmosphere.noiseOpacity).toBe(0.04);
	});

	it('has hexagon portrait frame', () => {
		expect(darkFantasy.portraitFrame.shape).toBe('hexagon');
	});

	it('has portrait frame glow', () => {
		expect(darkFantasy.portraitFrame.glow).toBe('0 0 8px #daa52033');
	});

	it('has 2px border radius', () => {
		expect(darkFantasy.details.borderRadius).toBe('2px');
	});

	it('has all 10 agent colors', () => {
		expect(Object.keys(darkFantasy.colors.agents)).toHaveLength(10);
	});

	it('covers all agent names', () => {
		for (const name of WELL_KNOWN_AGENTS) {
			expect(darkFantasy.colors.agents[name]).toBeDefined();
		}
	});

	it('uses jewel tone agent colors', () => {
		expect(darkFantasy.colors.agents.personal).toBe('#a855f7');
		expect(darkFantasy.colors.agents.work).toBe('#3b82f6');
		expect(darkFantasy.colors.agents.homelab).toBe('#06b6d4');
		expect(darkFantasy.colors.agents.finance).toBe('#10b981');
		expect(darkFantasy.colors.agents.email).toBe('#f59e0b');
			expect(darkFantasy.colors.agents.docs).toBe('#6366f1');
			expect(darkFantasy.colors.agents.music).toBe('#ec4899');
			expect(darkFantasy.colors.agents.home).toBe('#f97316');
			expect(darkFantasy.colors.agents.huginn).toBe('#9a8463');
			expect(darkFantasy.colors.agents.general).toBe('#8b7355');
		});

	it('colors use parchment primary text', () => {
		expect(darkFantasy.colors.textPrimary).toBe('#d4c5a9');
	});

	it('has dark warm canvas', () => {
		expect(darkFantasy.colors.canvas).toBe('#1a1510');
	});

	it('uses dark goldenrod border', () => {
		expect(darkFantasy.colors.border).toBe('#b8860b');
	});

	it('uses goldenrod emphasis and links', () => {
		expect(darkFantasy.colors.borderEmphasis).toBe('#daa520');
		expect(darkFantasy.colors.textLink).toBe('#daa520');
		expect(darkFantasy.colors.focus).toBe('#daa520');
	});

	it('has smooth portrait animation style', () => {
		expect(darkFantasy.animations.portraitStyle).toBe('smooth');
	});

	it('has 1.2 duration scale', () => {
		expect(darkFantasy.animations.durationScale).toBe(1.2);
	});

	it('code block uses catppuccin-mocha Shiki theme', () => {
		expect(darkFantasy.components.codeBlock.shikiTheme).toBe('catppuccin-mocha');
	});

	it('code block uses tab header style', () => {
		expect(darkFantasy.components.codeBlock.headerStyle).toBe('tab');
	});

	it('mode rail uses glow active indicator', () => {
		expect(darkFantasy.components.modeRail.activeIndicator).toBe('glow');
	});

	it('confirm card uses glow urgency and ring countdown', () => {
		expect(darkFantasy.components.confirmCard.urgencyStyle).toBe('glow');
		expect(darkFantasy.components.confirmCard.countdownStyle).toBe('ring');
	});

	it('sidebar uses hover-edge resize and glow indicator', () => {
		expect(darkFantasy.components.sidebar.resizeHandle).toBe('hover-edge');
		expect(darkFantasy.components.sidebar.activeSessionIndicator).toBe('glow');
	});

	it('details match design spec', () => {
		expect(darkFantasy.details.scrollbarWidth).toBe('thin');
		expect(darkFantasy.details.selectionBg).toBe('#daa52044');
		expect(darkFantasy.details.selectionText).toBe('#d4c5a9');
		expect(darkFantasy.details.textOnAccent).toBe('#1a1510');
		expect(darkFantasy.details.kbdStyle).toBe('beveled');
	});

	it('user message background is warm dark', () => {
		expect(darkFantasy.components.chatPanel.userMessageBg).toBe('#2a2015');
	});

	it('status bar uses sans font family', () => {
		expect(darkFantasy.components.statusBar.fontFamily).toBe('sans');
	});

	it('chat panel has 780px max width', () => {
		expect(darkFantasy.components.chatPanel.maxWidth).toBe('780px');
	});
});

describe('Tactical RTS theme', () => {
	it('has correct identity', () => {
		expect(tacticalRts.id).toBe('tactical-rts');
		expect(tacticalRts.name).toBe('Tactical RTS Command');
	});

	it('uses command-oriented typography', () => {
		expect(tacticalRts.fonts.sans.family).toBe('Rajdhani');
		expect(tacticalRts.fonts.mono.family).toBe('JetBrains Mono');
		expect(tacticalRts.fonts.display?.family).toBe('Orbitron');
	});

	it('uses stepped portrait style and fill mode rail indicator', () => {
		expect(tacticalRts.animations.portraitStyle).toBe('stepped');
		expect(tacticalRts.components.modeRail.activeIndicator).toBe('fill');
	});

	it('includes atmospheric tactical grid effect', () => {
		expect(tacticalRts.atmosphere.backgroundEffect).toBeDefined();
		expect(tacticalRts.atmosphere.backgroundEffect).toContain('repeating-linear-gradient');
	});
});

describe('Theme registry', () => {
	it('ops-cockpit is registered by default', () => {
		const theme = getTheme('ops-cockpit');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('ops-cockpit');
	});

	it('retro-terminal is registered by default', () => {
		const theme = getTheme('retro-terminal');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('retro-terminal');
	});

	it('dark-fantasy is registered by default', () => {
		const theme = getTheme('dark-fantasy');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('dark-fantasy');
	});

	it('tactical-rts is registered by default', () => {
		const theme = getTheme('tactical-rts');
		expect(theme).toBeDefined();
		expect(theme!.id).toBe('tactical-rts');
	});

	it('DEFAULT_THEME_ID is ops-cockpit', () => {
		expect(DEFAULT_THEME_ID).toBe('ops-cockpit');
	});

	it('lists all registered themes', () => {
		const themes = listThemes();
		expect(themes.length).toBeGreaterThanOrEqual(4);
		expect(themes.some((t) => t.id === 'ops-cockpit')).toBe(true);
		expect(themes.some((t) => t.id === 'retro-terminal')).toBe(true);
		expect(themes.some((t) => t.id === 'dark-fantasy')).toBe(true);
		expect(themes.some((t) => t.id === 'tactical-rts')).toBe(true);
	});

	it('getTheme returns undefined for unknown id', () => {
		expect(getTheme('nonexistent')).toBeUndefined();
	});

	it('registerTheme adds a new theme', () => {
		const custom: ThemeConfig = { ...createMinimalTheme(), id: 'custom-test', name: 'Custom Test' };
		registerTheme(custom);
		const retrieved = getTheme('custom-test');
		expect(retrieved).toBeDefined();
		expect(retrieved!.name).toBe('Custom Test');
	});

	it('registerTheme overwrites existing theme with same id', () => {
		const v1: ThemeConfig = { ...createMinimalTheme(), id: 'overwrite-test', name: 'V1' };
		const v2: ThemeConfig = { ...createMinimalTheme(), id: 'overwrite-test', name: 'V2' };
		registerTheme(v1);
		registerTheme(v2);
		expect(getTheme('overwrite-test')!.name).toBe('V2');
	});
});

function createMinimalTheme(): ThemeConfig {
	return {
		id: 'test-theme',
		name: 'Test Theme',
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
			textMuted: '#6e7681',
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
				fallback: 'ui-sans-serif, system-ui, sans-serif',
			},
			mono: {
				family: 'IBM Plex Mono',
				weights: [400, 500, 700],
				source: { type: 'google', family: 'IBM+Plex+Mono' },
				fallback: 'ui-monospace, monospace',
			},
		},
		atmosphere: {},
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
			statusBar: { background: 'var(--color-surface)', separator: '|', fontFamily: 'mono' },
			modeRail: { iconWeight: 1.5, activeIndicator: 'bar' },
			chatPanel: { userMessageBg: '#1c2333', assistantMessageBg: 'transparent', maxWidth: '900px', messagePadding: '16px' },
			toolCard: { statusBorderWidth: '2px', expandAnimation: 'slide' },
			confirmCard: { urgencyStyle: 'border', countdownStyle: 'bar' },
			codeBlock: { shikiTheme: 'github-dark', headerStyle: 'bar' },
			sidebar: { resizeHandle: 'custom-bar', activeSessionIndicator: 'left-border' },
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
}
