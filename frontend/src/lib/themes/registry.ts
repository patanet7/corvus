import type { ThemeConfig } from './types';
import { opsCockpit } from './themes/ops-cockpit';
import { retroTerminal } from './themes/retro-terminal';
import { darkFantasy } from './themes/dark-fantasy';
import { tacticalRts } from './themes/tactical-rts';

const themes = new Map<string, ThemeConfig>();

themes.set(opsCockpit.id, opsCockpit);
themes.set(retroTerminal.id, retroTerminal);
themes.set(darkFantasy.id, darkFantasy);
themes.set(tacticalRts.id, tacticalRts);

export function registerTheme(theme: ThemeConfig): void {
	themes.set(theme.id, theme);
}

export function getTheme(id: string): ThemeConfig | undefined {
	return themes.get(id);
}

export function listThemes(): ThemeConfig[] {
	return Array.from(themes.values());
}

export const DEFAULT_THEME_ID = 'ops-cockpit';
