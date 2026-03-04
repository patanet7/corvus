import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentPortrait from './AgentPortrait.svelte';

const meta = {
	title: 'Chat/AgentPortrait',
	component: AgentPortrait,
	tags: ['autodocs'],
	args: {
		agent: 'homelab',
		size: 'lg',
		status: 'idle'
	}
} satisfies Meta<typeof AgentPortrait>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {};

export const Thinking: Story = {
	args: {
		status: 'thinking'
	}
};

export const Streaming: Story = {
	args: {
		status: 'streaming'
	}
};

export const Error: Story = {
	args: {
		status: 'error'
	}
};
