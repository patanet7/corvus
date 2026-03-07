import type { Meta, StoryObj } from '@storybook/sveltekit';
import RecipientPicker from './RecipientPicker.svelte';
import { storyAgents } from './storybook-fixtures';

const meta = {
	title: 'Chat/RecipientPicker',
	component: RecipientPicker,
	tags: ['autodocs'],
	args: {
		availableAgents: storyAgents,
		selectedRecipients: [],
		sendToAll: false,
		onRecipientsChange: () => {}
	}
} satisfies Meta<typeof RecipientPicker>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const WithRecipient: Story = {
	args: {
		selectedRecipients: ['homelab']
	}
};

export const SendToAll: Story = {
	args: {
		sendToAll: true
	}
};
