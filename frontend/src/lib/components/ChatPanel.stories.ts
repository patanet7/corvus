import type { Meta, StoryObj } from '@storybook/sveltekit';
import ChatPanel from './ChatPanel.svelte';
import type { AgentInfo, ChatMessage, ModelInfo } from '$lib/types';

const models: ModelInfo[] = [
	{
		id: 'ollama/llama3:8b',
		label: 'llama3:8b',
		backend: 'ollama',
		available: true,
		description: 'Ollama local model'
	},
	{
		id: 'claude/sonnet-4-5',
		label: 'Claude Sonnet 4.5',
		backend: 'claude',
		available: false,
		description: 'Unavailable in this fixture'
	}
];

const agents: AgentInfo[] = [
	{
		id: 'general',
		label: 'General',
		isDefault: true,
		complexity: 'medium',
		memoryDomain: 'shared',
		toolModules: ['sessions', 'search'],
		hasPrompt: true
	},
	{
		id: 'work',
		label: 'Work',
		complexity: 'high',
		memoryDomain: 'work',
		toolModules: ['jira', 'github', 'calendar'],
		hasPrompt: true
	},
	{
		id: 'homelab',
		label: 'Homelab',
		complexity: 'high',
		memoryDomain: 'ops',
		toolModules: ['docker', 'tailscale', 'monitoring'],
		hasPrompt: true
	},
	{
		id: 'huginn',
		label: 'Huginn',
		complexity: 'medium',
		memoryDomain: 'router',
		toolModules: ['dispatch', 'routing'],
		hasPrompt: true
	}
];

const transcript: ChatMessage[] = [
	{
		id: 'u-1',
		role: 'user',
		content: '@homelab restart plex and check status',
		timestamp: new Date('2026-03-02T19:00:00Z')
	},
	{
		id: 'a-1',
		role: 'assistant',
		content: 'Restarted Plex and verified container is healthy.',
		agent: 'homelab',
		model: 'ollama/llama3:8b',
		timestamp: new Date('2026-03-02T19:00:03Z')
	}
];

const meta = {
	title: 'Chat/ChatPanel',
	component: ChatPanel,
	tags: ['autodocs'],
	args: {
		messages: [],
		activeAgent: null,
		agentStatus: 'idle',
		connectionStatus: 'connected',
		sessionName: 'Huginn',
		activeConfirmRequest: null,
		models,
		selectedModel: 'ollama/llama3:8b',
		contextPct: 34,
		modelModeLabel: 'Preferred',
		availableAgents: agents,
		pinnedAgent: null,
		dispatchMode: 'router',
		selectedRecipients: [],
		sendToAllRecipients: false,
		transcriptLoading: false,
		transcriptError: null,
		runtimeTask: null,
		onModelChange: () => {},
		onDispatchModeChange: () => {},
		onRecipientsChange: () => {},
		onSendMessage: () => {},
		onInterrupt: () => {},
		onConfirmRespond: () => {},
		onClearPinnedAgent: () => {},
		onReconnect: () => {},
		onRetryTranscript: () => {},
		onOpenToolTrace: () => {}
	}
} satisfies Meta<typeof ChatPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const WithTranscript: Story = {
	args: {
		messages: transcript,
		activeAgent: 'homelab',
		agentStatus: 'done'
	}
};

export const WithPinnedAgent: Story = {
	args: {
		messages: transcript,
		pinnedAgent: 'work'
	}
};

export const ContextFull: Story = {
	args: {
		messages: transcript,
		activeAgent: 'work',
		selectedModel: 'claude/sonnet-4-5',
		contextPct: 99
	}
};
