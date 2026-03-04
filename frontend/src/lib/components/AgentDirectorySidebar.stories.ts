import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentDirectorySidebar from './AgentDirectorySidebar.svelte';

const meta = {
	title: 'Agents/AgentDirectorySidebar',
	component: AgentDirectorySidebar,
	tags: ['autodocs'],
	args: {
		width: 280,
		loading: false,
		error: null,
		activeAgentId: 'homelab',
		agents: [
			{
				id: 'homelab',
				label: 'Homelab',
				description: 'Infrastructure and service management',
				runtimeStatus: 'busy',
				currentModel: 'ollama/qwen3:8b',
				queueDepth: 2
			},
			{
				id: 'work',
				label: 'Work',
				description: 'Project and planning assistant',
				runtimeStatus: 'active',
				currentModel: 'claude/sonnet-4-6',
				queueDepth: 0
			},
			{
				id: 'finance',
				label: 'Finance',
				description: 'Budgeting and account insights',
				runtimeStatus: 'degraded',
				queueDepth: 1
			}
		],
		onSelectAgent: () => {},
		onRefresh: () => {}
	}
} satisfies Meta<typeof AgentDirectorySidebar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Loading: Story = {
	args: {
		loading: true
	}
};

export const Error: Story = {
	args: {
		error: 'Failed to load agent directory.'
	}
};
