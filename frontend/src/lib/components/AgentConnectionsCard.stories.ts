import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentConnectionsCard from './AgentConnectionsCard.svelte';

const meta = {
	title: 'Agents/Cards/Connections',
	component: AgentConnectionsCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'homelab',
			label: 'Homelab',
			runtimeStatus: 'busy',
			toolModules: ['ha', 'paperless', 'obsidian']
		},
		profile: {
			id: 'homelab',
			label: 'Homelab',
			description: 'Infra automation',
			enabled: true,
			autoModelRouting: true,
			readableDomains: ['homelab', 'shared'],
			canReadShared: true,
			canWriteMemory: true,
			builtinTools: ['Bash'],
			confirmGatedTools: ['ha.call_service'],
			moduleConfig: {
				ha: {},
				paperless: {},
				obsidian: {}
			},
			metadata: {},
			recentRuns: []
		},
		moduleHealthByName: {
			ha: { name: 'ha', status: 'healthy', message: 'Connected' },
			paperless: { name: 'paperless', status: 'degraded', message: 'Token expires soon' },
			obsidian: { name: 'obsidian', status: 'error', message: 'API key missing' }
		}
	}
} satisfies Meta<typeof AgentConnectionsCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const MixedHealth: Story = {};

export const Offline: Story = {
	args: {
		agent: {
			id: 'homelab',
			label: 'Homelab',
			runtimeStatus: 'offline',
			toolModules: ['ha']
		},
		moduleHealthByName: {}
	}
};
