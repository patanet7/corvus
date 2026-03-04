import type { Meta, StoryObj } from '@storybook/sveltekit';
import ToastStack from './ToastStack.svelte';
import { toastStore } from '$lib/chat/toasts.svelte';

const meta = {
	title: 'Feedback/ToastStack',
	component: ToastStack,
	tags: ['autodocs'],
	parameters: {
		layout: 'fullscreen'
	}
} satisfies Meta<typeof ToastStack>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
	render: () => {
		toastStore.items = [];
		return {
			Component: ToastStack
		};
	}
};

export const Mixed: Story = {
	render: () => {
		toastStore.items = [
			{
				id: 'toast-1',
				kind: 'success',
				message: 'Chat connection restored.',
				createdAt: new Date()
			},
			{
				id: 'toast-2',
				kind: 'warning',
				message: 'Attachments are staged only at UI level.',
				createdAt: new Date()
			},
			{
				id: 'toast-3',
				kind: 'error',
				message: 'Selected model is unavailable.',
				createdAt: new Date()
			}
		];
		return {
			Component: ToastStack
		};
	}
};
