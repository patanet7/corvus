import type { AgentName } from '$lib/types';

const STORAGE_KEY = 'corvus.chat.model-preferences.v1';

export type ModelPreferences = Partial<Record<AgentName, string>>;

export function loadModelPreferences(): ModelPreferences {
	if (typeof localStorage === 'undefined') return {};
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return {};
		const parsed = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object') return {};
		const prefs: ModelPreferences = {};
		for (const [key, value] of Object.entries(parsed)) {
			if (typeof value === 'string' && value.trim()) {
				prefs[key as AgentName] = value;
			}
		}
		return prefs;
	} catch {
		return {};
	}
}

export function saveModelPreferences(prefs: ModelPreferences): void {
	if (typeof localStorage === 'undefined') return;
	localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}

export function preferredModelForAgent(
	agent: AgentName | null | undefined,
	prefs: ModelPreferences
): string | null {
	if (!agent) return null;
	const value = prefs[agent];
	return typeof value === 'string' && value.trim() ? value : null;
}
