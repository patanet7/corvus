import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentIdentityChip from './AgentIdentityChip.svelte';

const meta = {
	title: 'Chat/AgentIdentityChip',
	component: AgentIdentityChip,
	tags: ['autodocs'],
	args: {
		agent: 'homelab',
		model: 'ollama/llama3:8b',
		size: 'sm'
	}
} satisfies Meta<typeof AgentIdentityChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const AgentOnly: Story = {
	args: {
		model: null
	}
};

export const Medium: Story = {
	args: {
		size: 'md',
		agent: 'work',
		model: 'claude/sonnet-4-5'
	}
};
