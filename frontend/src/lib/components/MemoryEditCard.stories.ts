import type { Meta, StoryObj } from '@storybook/sveltekit';
import MemoryEditCard from './MemoryEditCard.svelte';

const meta = {
	title: 'Workspace/MemoryEditCard',
	component: MemoryEditCard,
	tags: ['autodocs']
} satisfies Meta<typeof MemoryEditCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
	args: {
		record: null,
		enabled: true,
		loading: false
	}
};

export const Editable: Story = {
	args: {
		record: {
			id: 'memory-1',
			content: 'Meeting notes from the architecture review.',
			domain: 'work',
			visibility: 'private',
			importance: 0.7,
			tags: ['notes', 'architecture'],
			source: 'ui:storybook',
			createdAt: new Date('2026-03-03T12:00:00Z'),
			updatedAt: null,
			deletedAt: null,
			score: 0.82,
			metadata: { topic: 'chat-ui' }
		},
		enabled: true,
		loading: false
	}
};

export const Updating: Story = {
	args: {
		record: {
			id: 'memory-2',
			content: 'Updated policy exception request pending approval.',
			domain: 'ops',
			visibility: 'shared',
			importance: 0.6,
			tags: ['policy', 'approval'],
			source: 'ui:storybook',
			createdAt: new Date('2026-03-03T12:00:00Z'),
			updatedAt: new Date('2026-03-03T14:20:00Z'),
			deletedAt: null,
			score: 0.55,
			metadata: {}
		},
		enabled: true,
		loading: true
	}
};
