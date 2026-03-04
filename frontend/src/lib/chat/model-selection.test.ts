import { describe, expect, it } from 'vitest';

import type { ModelInfo } from '$lib/types';
import { resolveFallbackModelId, resolvePreferredModelId } from './model-selection';

const MODELS: ModelInfo[] = [
	{
		id: 'sonnet',
		label: 'Sonnet',
		backend: 'claude',
		available: true
	},
	{
		id: 'ollama/llama3:8b',
		label: 'Llama 3 8B',
		backend: 'ollama',
		available: true
	},
	{
		id: 'ollama/qwen3:8b',
		label: 'Qwen 3 8B',
		backend: 'ollama',
		available: true
	}
];

describe('resolvePreferredModelId', () => {
	it('uses configured default when it is available', () => {
		expect(resolvePreferredModelId('ollama/llama3:8b', MODELS)).toBe('ollama/llama3:8b');
	});

	it('falls back to first available model when configured default is unavailable', () => {
		expect(resolvePreferredModelId('opus', MODELS)).toBe('sonnet');
	});
});

describe('resolveFallbackModelId', () => {
	it('prefers last routed available model', () => {
		expect(
			resolveFallbackModelId({
				failedModelId: 'ollama/llama3:8b',
				defaultModelId: 'sonnet',
				lastRoutedModelId: 'ollama/qwen3:8b',
				models: MODELS
			})
		).toBe('ollama/qwen3:8b');
	});

	it('prefers configured default when last routed is unavailable', () => {
		expect(
			resolveFallbackModelId({
				failedModelId: 'ollama/llama3:8b',
				defaultModelId: 'sonnet',
				lastRoutedModelId: 'missing/model',
				models: MODELS
			})
		).toBe('sonnet');
	});

	it('uses same-backend candidate before global fallback', () => {
		expect(
			resolveFallbackModelId({
				failedModelId: 'ollama/llama3:8b',
				defaultModelId: 'missing/model',
				lastRoutedModelId: null,
				models: MODELS
			})
		).toBe('ollama/qwen3:8b');
	});

	it('returns null when no alternative exists', () => {
		expect(
			resolveFallbackModelId({
				failedModelId: 'sonnet',
				defaultModelId: 'sonnet',
				lastRoutedModelId: null,
				models: [{ id: 'sonnet', label: 'Sonnet', backend: 'claude', available: true }]
			})
		).toBeNull();
	});
});
