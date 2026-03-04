import type { Meta, StoryObj } from '@storybook/sveltekit';
import ServiceConnectionsCard from './ServiceConnectionsCard.svelte';

const meta = {
	title: 'Agents/Cards/ServiceConnections',
	component: ServiceConnectionsCard,
	tags: ['autodocs'],
	args: {
		connections: [
			{ id: 'memory', label: 'Memory Hub', status: 'active', detail: 'Healthy and synced' },
			{ id: 'obsidian', label: 'Obsidian Vault', status: 'degraded', detail: 'High latency' },
			{ id: 'paperless', label: 'Paperless', status: 'offline', detail: 'Auth token expired' }
		]
	}
} satisfies Meta<typeof ServiceConnectionsCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
