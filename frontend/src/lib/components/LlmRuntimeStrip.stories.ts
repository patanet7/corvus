import type { Meta, StoryObj } from '@storybook/sveltekit';
import LlmRuntimeStrip from './LlmRuntimeStrip.svelte';
import type { ModelInfo } from '$lib/types';

const models: ModelInfo[] = [
	{
		id: 'ollama/llama3:8b',
		label: 'llama3:8b',
		backend: 'ollama',
		available: true,
		isDefault: true,
		capabilities: {
			supports_tools: true,
			supports_streaming: true
		}
	},
	{
		id: 'claude/sonnet-4-5',
		label: 'Claude Sonnet 4.5',
		backend: 'claude',
		available: false,
		capabilities: {
			supports_tools: true,
			supports_streaming: true
		}
	}
];

const meta = {
	title: 'Chat/LlmRuntimeStrip',
	component: LlmRuntimeStrip,
	tags: ['autodocs'],
	args: {
		selectedModel: 'ollama/llama3:8b',
		models,
		contextPct: 44
	}
} satisfies Meta<typeof LlmRuntimeStrip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Stable: Story = {};

export const ContextHigh: Story = {
	args: {
		contextPct: 81
	}
};

export const ContextFull: Story = {
	args: {
		selectedModel: 'claude/sonnet-4-5',
		contextPct: 99
	}
};
