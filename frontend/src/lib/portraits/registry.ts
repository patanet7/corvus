import type { PortraitConfig } from './types';
import { DEFAULT_PORTRAITS } from './defaults';

const customPortraits = new Map<string, PortraitConfig>();

/** Fallback portrait for unknown agents — generic crow silhouette. */
const FALLBACK_PORTRAIT: PortraitConfig = DEFAULT_PORTRAITS['general'];

/** Get the portrait config for an agent. Custom portraits override defaults. Unknown agents get a fallback. */
export function getPortrait(agent: string): PortraitConfig {
	return customPortraits.get(agent) ?? DEFAULT_PORTRAITS[agent] ?? { ...FALLBACK_PORTRAIT, agent };
}

/** Register a custom portrait for an agent. Overrides the default. */
export function registerPortrait(config: PortraitConfig): void {
	customPortraits.set(config.agent, config);
}

/** Clear a custom portrait, reverting to the default. */
export function clearPortrait(agent: string): void {
	customPortraits.delete(agent);
}

/** List portrait configs for known agents. */
export function listPortraits(agentIds?: string[]): PortraitConfig[] {
	const ids = agentIds ?? Object.keys(DEFAULT_PORTRAITS);
	return ids.map(getPortrait);
}

/** Reset all custom portraits to defaults. Useful for testing. */
export function resetPortraits(): void {
	customPortraits.clear();
}
