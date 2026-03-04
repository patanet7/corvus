import { getContext, hasContext } from 'svelte';
import { DEFAULT_THEME_ID, getTheme } from './registry';
import type { ThemeConfig } from './types';

export const THEME_KEY = Symbol('corvus-theme');

export interface ThemeContext {
	readonly theme: ThemeConfig;
	setTheme: (id: string) => void;
}

export function getThemeContext(): ThemeContext {
	if (!hasContext(THEME_KEY)) {
		const fallbackTheme = getTheme(DEFAULT_THEME_ID);
		if (!fallbackTheme) {
			throw new Error(`Default theme "${DEFAULT_THEME_ID}" not found`);
		}
		return {
			theme: fallbackTheme,
			setTheme: () => {}
		};
	}
	return getContext<ThemeContext>(THEME_KEY);
}
