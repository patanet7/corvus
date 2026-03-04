import type { Meta, StoryObj } from '@storybook/sveltekit';
import ModelSelector from './ModelSelector.svelte';
import type { ModelInfo } from '$lib/types';

const models: ModelInfo[] = [
	{
		id: 'ollama/llama3:8b',
		label: 'llama3:8b',
		backend: 'ollama',
		available: true,
		description: 'Fast local inference',
		isDefault: true
	},
	{
		id: 'claude/sonnet-4-5',
		label: 'Claude Sonnet 4.5',
		backend: 'claude',
		available: false,
		description: 'Remote provider unavailable'
	}
];

const meta = {
	title: 'Chat/ModelSelector',
	component: ModelSelector,
	tags: ['autodocs'],
	args: {
		models,
		selectedModel: 'ollama/llama3:8b',
		modeLabel: 'Preferred',
		onModelChange: () => {}
	}
} satisfies Meta<typeof ModelSelector>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const ManualOverride: Story = {
	args: {
		modeLabel: 'Manual',
		selectedModel: 'claude/sonnet-4-5'
	}
};

