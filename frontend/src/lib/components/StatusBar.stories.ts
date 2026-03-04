import type { Meta, StoryObj } from '@storybook/sveltekit';
import StatusBar from './StatusBar.svelte';

const meta = {
	title: 'Layout/StatusBar',
	component: StatusBar,
	tags: ['autodocs'],
	args: {
		connectionStatus: 'connected',
		activeAgent: 'homelab',
		sessionName: 'Huginn',
		costUsd: 0.27,
		tokensUsed: 1821,
		contextPct: 46
	}
} satisfies Meta<typeof StatusBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Connected: Story = {};

export const ConnectingNoMetrics: Story = {
	args: {
		connectionStatus: 'connecting',
		activeAgent: null,
		costUsd: 0,
		tokensUsed: 0,
		contextPct: 0
	}
};

export const ContextCritical: Story = {
	args: {
		contextPct: 99
	}
};
