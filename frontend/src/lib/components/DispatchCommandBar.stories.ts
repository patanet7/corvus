import type { Meta, StoryObj } from '@storybook/sveltekit';
import DispatchCommandBar from './DispatchCommandBar.svelte';

const meta = {
	title: 'Tasks/DispatchCommandBar',
	component: DispatchCommandBar,
	tags: ['autodocs'],
	args: {
		activeCount: 3,
		paused: false
	}
} satisfies Meta<typeof DispatchCommandBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Paused: Story = {
	args: {
		paused: true
	}
};
