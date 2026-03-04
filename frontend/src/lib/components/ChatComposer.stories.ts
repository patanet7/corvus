import type { Meta, StoryObj } from '@storybook/sveltekit';
import ChatComposer from './ChatComposer.svelte';
import { storyAgents, storyModels } from './storybook-fixtures';

const meta = {
	title: 'Chat/ChatComposer',
	component: ChatComposer,
	tags: ['autodocs'],
	args: {
		models: storyModels,
		selectedModel: 'ollama/llama3:8b',
		modelModeLabel: 'Preferred',
		availableAgents: storyAgents,
		dispatchMode: 'router',
		selectedRecipients: [],
		sendToAllRecipients: false,
		isStreaming: false,
		onModelChange: () => {},
		onDispatchModeChange: () => {},
		onRecipientsChange: () => {},
		onSendMessage: () => {},
		onInterrupt: () => {}
	}
} satisfies Meta<typeof ChatComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {};

export const DirectRecipient: Story = {
	args: {
		dispatchMode: 'direct',
		selectedRecipients: ['homelab']
	}
};

export const Streaming: Story = {
	args: {
		isStreaming: true
	}
};
