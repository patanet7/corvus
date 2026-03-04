import type { Meta, StoryObj } from '@storybook/sveltekit';
import ChatHeaderBar from './ChatHeaderBar.svelte';
import { storyAgents, storyModels } from './storybook-fixtures';

const meta = {
	title: 'Chat/ChatHeaderBar',
	component: ChatHeaderBar,
	tags: ['autodocs'],
	args: {
		activeAgent: 'homelab',
		agentStatus: 'idle',
		sessionName: 'Huginn',
		pinnedAgent: null,
		activeAgentInfo: storyAgents.find((agent) => agent.id === 'homelab') ?? null,
		selectedModel: 'ollama/llama3:8b',
		models: storyModels,
		contextPct: 42,
		onClearPinnedAgent: () => {}
	}
} satisfies Meta<typeof ChatHeaderBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {};

export const StreamingPinned: Story = {
	args: {
		agentStatus: 'streaming',
		pinnedAgent: 'work'
	}
};
