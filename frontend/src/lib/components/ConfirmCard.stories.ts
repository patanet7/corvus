import type { Meta, StoryObj } from '@storybook/sveltekit';
import ConfirmCard from './ConfirmCard.svelte';
import { storyConfirmRequest } from './storybook-fixtures';

const meta = {
	title: 'Chat/ConfirmCard',
	component: ConfirmCard,
	tags: ['autodocs'],
	args: {
		confirmRequest: storyConfirmRequest,
		onRespond: () => {}
	}
} satisfies Meta<typeof ConfirmCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const NearTimeout: Story = {
	args: {
		confirmRequest: {
			...storyConfirmRequest,
			timeoutS: 8,
			createdAt: new Date(Date.now() - 6_500)
		}
	}
};
