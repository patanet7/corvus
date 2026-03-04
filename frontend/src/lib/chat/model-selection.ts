import type { ModelInfo } from '$lib/types';

function modelExists(models: ModelInfo[], id: string): boolean {
	return models.some((model) => model.id === id && model.available);
}

function modelBackend(id: string, models: ModelInfo[]): string | null {
	if (id.includes('/')) {
		return id.split('/', 1)[0] ?? null;
	}
	return models.find((model) => model.id === id)?.backend ?? null;
}

export function resolvePreferredModelId(defaultModelId: string, models: ModelInfo[]): string {
	if (defaultModelId && modelExists(models, defaultModelId)) {
		return defaultModelId;
	}
	return models[0]?.id ?? defaultModelId ?? '';
}

export function resolveFallbackModelId(params: {
	failedModelId: string;
	defaultModelId: string;
	lastRoutedModelId: string | null;
	models: ModelInfo[];
}): string | null {
	const { failedModelId, defaultModelId, lastRoutedModelId, models } = params;
	const available = models.filter((model) => model.available);
	if (available.length === 0) return null;

	const firstDifferent = (candidates: Array<string | null | undefined>): string | null => {
		for (const candidate of candidates) {
			if (!candidate || candidate === failedModelId) continue;
			if (modelExists(models, candidate)) return candidate;
		}
		return null;
	};

	const direct = firstDifferent([lastRoutedModelId, defaultModelId]);
	if (direct) return direct;

	const failedBackend = modelBackend(failedModelId, models);
	if (failedBackend) {
		const sameBackend = available.find(
			(model) => model.backend === failedBackend && model.id !== failedModelId
		);
		if (sameBackend) return sameBackend.id;
	}

	return available.find((model) => model.id !== failedModelId)?.id ?? null;
}
