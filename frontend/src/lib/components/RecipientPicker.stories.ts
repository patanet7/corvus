import type { Meta, StoryObj } from '@storybook/sveltekit';
import RecipientPicker from './RecipientPicker.svelte';
import { storyAgents } from './storybook-fixtures';

const meta = {
	title: 'Chat/RecipientPicker',
	component: RecipientPicker,
	tags: ['autodocs'],
	args: {
		availableAgents: storyAgents,
		dispatchMode: 'router',
		selectedRecipients: [],
		sendToAll: false,
		onDispatchModeChange: () => {},
		onRecipientsChange: () => {}
	}
} satisfies Meta<typeof RecipientPicker>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Router: Story = {};

export const Direct: Story = {
	args: {
		dispatchMode: 'direct',
		selectedRecipients: ['homelab']
	}
};

export const ParallelAll: Story = {
	args: {
		dispatchMode: 'parallel',
		sendToAll: true
	}
};
