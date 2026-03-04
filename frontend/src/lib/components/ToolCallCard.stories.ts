import type { Meta, StoryObj } from '@storybook/sveltekit';
import ToolCallCard from './ToolCallCard.svelte';

const meta = {
	title: 'Chat/ToolCallCard',
	component: ToolCallCard,
	tags: ['autodocs'],
	args: {
		toolCall: {
			callId: 'call-9f1a',
			tool: 'search_web',
			params: {
				query: 'status of plex container',
				timeout: 30
			},
			status: 'success',
			durationMs: 842,
			output: 'Container is healthy; restart count has not changed.'
		},
		onOpenTrace: () => {}
	}
} satisfies Meta<typeof ToolCallCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Success: Story = {};

export const Running: Story = {
	args: {
		toolCall: {
			callId: 'call-running',
			tool: 'tail_logs',
			params: { container: 'plex', lines: 120 },
			status: 'running'
		}
	}
};

export const Error: Story = {
	args: {
		toolCall: {
			callId: 'call-error',
			tool: 'restart_service',
			params: { service: 'plex' },
			status: 'error',
			durationMs: 1304,
			output: 'Permission denied while restarting service.'
		}
	}
};
