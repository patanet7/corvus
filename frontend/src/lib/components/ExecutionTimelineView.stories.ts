import type { Meta, StoryObj } from '@storybook/sveltekit';
import ExecutionTimelineView from './ExecutionTimelineView.svelte';

const meta = {
	title: 'Tasks/ExecutionTimelineView',
	component: ExecutionTimelineView,
	tags: ['autodocs'],
	args: {
		blocks: [
			{
				id: 'b1',
				kind: 'prompt',
				title: 'Prompt',
				content: '@homelab investigate docker timeout',
				timestamp: '14:32:00'
			},
			{
				id: 'b2',
				kind: 'tool',
				title: 'Tool',
				content: 'mcp__memory_homelab__query',
				meta: 'call_id=tool-123',
				timestamp: '14:32:02'
			},
			{
				id: 'b3',
				kind: 'output',
				title: 'Output',
				content: 'Detected timeout pattern in plex logs.',
				timestamp: '14:32:10'
			}
		]
	}
} satisfies Meta<typeof ExecutionTimelineView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
