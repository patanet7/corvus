import type { Meta, StoryObj } from '@storybook/sveltekit';
import PermissionDecisionFeedCard from './PermissionDecisionFeedCard.svelte';

const meta = {
	title: 'Security/PermissionDecisionFeedCard',
	component: PermissionDecisionFeedCard,
	tags: ['autodocs'],
	args: {
		events: [
			{
				id: 'perm-1',
				timestamp: '10:24:31',
				agent: 'homelab',
				tool: 'Bash',
				state: 'allow',
				scope: 'builtin',
				reason: 'Tool listed in builtin allow policy.'
			},
			{
				id: 'perm-2',
				timestamp: '10:24:45',
				agent: 'finance',
				tool: 'mcp__firefly__create_transaction',
				state: 'confirm',
				scope: 'confirm_gated',
				reason: 'Transaction writes require explicit user confirmation.'
			},
			{
				id: 'perm-3',
				timestamp: '10:25:02',
				agent: 'docs',
				tool: 'mcp__paperless__paperless_search',
				state: 'deny',
				scope: 'module',
				reason: 'Missing env: PAPERLESS_URL, PAPERLESS_API_TOKEN'
			}
		]
	}
} satisfies Meta<typeof PermissionDecisionFeedCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Empty: Story = {
	args: {
		events: []
	}
};

export const Loading: Story = {
	args: {
		loading: true
	}
};
