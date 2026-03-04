import type { Meta, StoryObj } from '@storybook/sveltekit';
import ErrorBanner from './ErrorBanner.svelte';

const meta = {
	title: 'Chat/ErrorBanner',
	component: ErrorBanner,
	tags: ['autodocs'],
	args: {
		message: 'Selected model cannot execute this tool-enabled request.',
		dismissible: false
	}
} satisfies Meta<typeof ErrorBanner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Dismissible: Story = {
	args: {
		dismissible: true,
		onDismiss: () => {}
	}
};
