import type { Meta, StoryObj } from '@storybook/sveltekit';
import SecurityDomainSidebar from './SecurityDomainSidebar.svelte';

const meta = {
	title: 'Security/SecurityDomainSidebar',
	component: SecurityDomainSidebar,
	tags: ['autodocs'],
	args: {
		domains: [
			{ id: 'fs', label: 'File System', count: 12, icon: 'fs', sensitivity: 'high' },
			{ id: 'network', label: 'Network', count: 8, icon: 'net', sensitivity: 'medium' },
			{ id: 'memory', label: 'Memory', count: 5, icon: 'mem', sensitivity: 'low' }
		],
		selectedDomainId: 'fs',
		agentScopes: [
			{ id: 'homelab', status: 'active' },
			{ id: 'finance', status: 'idle' },
			{ id: 'work', status: 'offline' }
		]
	}
} satisfies Meta<typeof SecurityDomainSidebar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Empty: Story = {
	args: {
		domains: [],
		agentScopes: []
	}
};
