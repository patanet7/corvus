import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentSpecialtyAccess from './AgentSpecialtyAccess.svelte';
import type { AgentInfo } from '$lib/types';

const agent: AgentInfo = {
	id: 'homelab',
	label: 'Homelab',
	description: 'Infrastructure and operations specialist.',
	complexity: 'high',
	memoryDomain: 'ops',
	toolModules: ['docker', 'komodo', 'tailscale', 'monitoring', 'storage'],
	hasPrompt: true
};

const meta = {
	title: 'Agents/AgentSpecialtyAccess',
	component: AgentSpecialtyAccess,
	tags: ['autodocs'],
	args: {
		agent,
		compact: false
	}
} satisfies Meta<typeof AgentSpecialtyAccess>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Full: Story = {};

export const Compact: Story = {
	args: {
		compact: true
	}
};

export const NoSpecialty: Story = {
	args: {
		agent: {
			id: 'general',
			label: 'General',
			complexity: 'low',
			hasPrompt: false
		}
	}
};
