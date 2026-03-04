import type { Meta, StoryObj } from '@storybook/sveltekit';
import MessageRuntimeTimeline from './MessageRuntimeTimeline.svelte';

const now = Date.now();

const meta = {
	title: 'Chat/MessageRuntimeTimeline',
	component: MessageRuntimeTimeline,
	tags: ['autodocs'],
	args: {
		streaming: true,
		events: [
			{
				id: 'evt-1',
				kind: 'thinking',
				summary: 'Routing request to homelab agent.',
				timestamp: new Date(now - 8_000)
			},
			{
				id: 'evt-2',
				kind: 'tool_start',
				summary: 'Starting docker.logs tool call.',
				timestamp: new Date(now - 5_000),
				callId: 'call-123',
				detail: '{"service":"plex"}'
			},
			{
				id: 'evt-3',
				kind: 'tool_result',
				summary: 'Tool completed successfully.',
				timestamp: new Date(now - 3_000),
				callId: 'call-123',
				detail: 'Found 2 warning lines.'
			},
			{
				id: 'evt-4',
				kind: 'todo',
				summary: 'TODO: restart plex and verify health checks.',
				timestamp: new Date(now - 2_000)
			},
			{
				id: 'evt-5',
				kind: 'result',
				summary: 'Run completed.',
				timestamp: new Date(now - 800)
			}
		],
		onOpenTrace: () => {}
	}
} satisfies Meta<typeof MessageRuntimeTimeline>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const IdleCollapsed: Story = {
	args: {
		streaming: false
	}
};
