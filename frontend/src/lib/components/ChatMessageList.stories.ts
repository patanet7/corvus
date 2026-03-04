import type { Meta, StoryObj } from '@storybook/sveltekit';
import ChatMessageList from './ChatMessageList.svelte';
import { storyMessages, storyTask } from './storybook-fixtures';

const meta = {
	title: 'Chat/ChatMessageList',
	component: ChatMessageList,
	tags: ['autodocs'],
	args: {
		messages: storyMessages,
		agentStatus: 'done',
		connectionStatus: 'connected',
		shikiTheme: 'github-dark',
		onReconnect: () => {},
		loadingTranscript: false,
		transcriptError: null,
		onRetryTranscript: () => {},
		runtimeTask: null,
		onOpenToolTrace: () => {}
	}
} satisfies Meta<typeof ChatMessageList>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithMessages: Story = {};

export const LoadingTranscript: Story = {
	args: {
		messages: [],
		loadingTranscript: true
	}
};

export const WithRuntimeTask: Story = {
	args: {
		agentStatus: 'streaming',
		runtimeTask: storyTask()
	}
};

export const TranscriptError: Story = {
	args: {
		messages: [],
		transcriptError: 'Unable to load transcript for this session.'
	}
};
