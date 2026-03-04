import type { AgentInfo, ModelInfo } from '$lib/types';
import { AGENT_NAMES } from '$lib/types';

export function modelModeLabelForSelection(
	mode: 'preferred' | 'manual',
	selectedModelId: string,
	models: ModelInfo[]
): 'Preferred' | 'Manual' | 'Unavailable' {
	if (mode === 'preferred') return 'Preferred';
	const selected = models.find((m) => m.id === selectedModelId);
	if (selected && !selected.available) return 'Unavailable';
	return 'Manual';
}

export function agentSuggestionSource(availableAgents: AgentInfo[]): string[] {
	if (availableAgents.length > 0) {
		return availableAgents.map((a) => a.id);
	}
	return [...AGENT_NAMES];
}
