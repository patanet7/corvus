import type { AgentName } from '$lib/types';
import { AGENT_NAMES } from '$lib/types';
import type { PortraitConfig } from './types';
import { DEFAULT_PORTRAITS } from './defaults';

const customPortraits = new Map<AgentName, PortraitConfig>();

/** Get the portrait config for an agent. Custom portraits override defaults. */
export function getPortrait(agent: AgentName): PortraitConfig {
	return customPortraits.get(agent) ?? DEFAULT_PORTRAITS[agent];
}

/** Register a custom portrait for an agent. Overrides the default. */
export function registerPortrait(config: PortraitConfig): void {
	customPortraits.set(config.agent, config);
}

/** Clear a custom portrait, reverting to the default. */
export function clearPortrait(agent: AgentName): void {
	customPortraits.delete(agent);
}

/** List portrait configs for all agents. */
export function listPortraits(): PortraitConfig[] {
	return AGENT_NAMES.map(getPortrait);
}

/** Reset all custom portraits to defaults. Useful for testing. */
export function resetPortraits(): void {
	customPortraits.clear();
}
