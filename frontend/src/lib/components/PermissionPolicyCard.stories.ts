import type { Meta, StoryObj } from '@storybook/sveltekit';
import PermissionPolicyCard from './PermissionPolicyCard.svelte';

const meta = {
	title: 'Security/PermissionPolicyCard',
	component: PermissionPolicyCard,
	tags: ['autodocs'],
	args: {
		toolId: 'mcp__obsidian_work__write',
		description: 'Write markdown content into work vault',
		state: 'confirm',
		risk: 'high',
		trustScore: 42,
		requiresConfirm: true,
		reason: 'Write operations require approval for this domain.'
	}
} satisfies Meta<typeof PermissionPolicyCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Confirm: Story = {};

export const Allow: Story = {
	args: {
		state: 'allow',
		risk: 'low',
		trustScore: 96,
		requiresConfirm: false
	}
};

export const Deny: Story = {
	args: {
		state: 'deny',
		risk: 'critical',
		trustScore: 8,
		requiresConfirm: false,
		reason: 'Module offline and policy is deny-by-default.'
	}
};
