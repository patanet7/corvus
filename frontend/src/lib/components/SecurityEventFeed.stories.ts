import type { Meta, StoryObj } from '@storybook/sveltekit';
import SecurityEventFeed from './SecurityEventFeed.svelte';

const meta = {
	title: 'Security/SecurityEventFeed',
	component: SecurityEventFeed,
	tags: ['autodocs'],
	args: {
		live: true,
		events: [
			{
				id: '1',
				timestamp: '14:32:05',
				agent: 'homelab',
				action: 'Execute rm -rf /var/log/plex/*',
				detail: 'Pending user confirmation',
				status: 'confirm',
				callId: 'call-123'
			},
			{
				id: '2',
				timestamp: '14:31:42',
				agent: 'finance',
				action: 'HTTP GET /costs',
				status: 'allowed'
			},
			{
				id: '3',
				timestamp: '14:30:15',
				agent: 'work',
				action: 'Delete local workspace cache',
				status: 'denied',
				detail: 'Policy state deny'
			}
		]
	}
} satisfies Meta<typeof SecurityEventFeed>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Empty: Story = {
	args: {
		events: [],
		live: false
	}
};
