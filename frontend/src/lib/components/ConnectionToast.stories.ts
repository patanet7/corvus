import type { Meta, StoryObj } from '@storybook/sveltekit';
import ConnectionToast from './ConnectionToast.svelte';

const meta = {
	title: 'Chat/ConnectionToast',
	component: ConnectionToast,
	tags: ['autodocs'],
	args: {
		status: 'disconnected',
		onReconnect: () => {}
	}
} satisfies Meta<typeof ConnectionToast>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Disconnected: Story = {};

export const Error: Story = {
	args: {
		status: 'error'
	}
};

export const ConnectedHidden: Story = {
	args: {
		status: 'connected'
	}
};
