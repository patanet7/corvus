import type { Meta, StoryObj } from '@storybook/sveltekit';
import MemoryAgentContextCard from './MemoryAgentContextCard.svelte';

const meta = {
	title: 'Workspace/MemoryAgentContextCard',
	component: MemoryAgentContextCard,
	tags: ['autodocs']
} satisfies Meta<typeof MemoryAgentContextCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Writable: Story = {
	args: {
		loading: false,
		agent: {
			id: 'homelab',
			label: 'Homelab',
			memoryDomain: 'homelab',
			canWrite: true,
			canReadShared: true,
			readablePrivateDomains: ['homelab']
		}
	}
};

export const ReadOnly: Story = {
	args: {
		loading: false,
		agent: {
			id: 'observer',
			label: 'Observer',
			memoryDomain: 'shared',
			canWrite: false,
			canReadShared: true,
			readablePrivateDomains: []
		}
	}
};
