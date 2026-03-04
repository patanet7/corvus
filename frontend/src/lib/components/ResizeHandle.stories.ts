import type { Meta, StoryObj } from '@storybook/sveltekit';
import ResizeHandle from './ResizeHandle.svelte';

const meta = {
	title: 'Layout/ResizeHandle',
	component: ResizeHandle,
	tags: ['autodocs'],
	args: {
		direction: 'horizontal',
		onResize: () => {}
	},
	parameters: {
		layout: 'centered'
	}
} satisfies Meta<typeof ResizeHandle>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Horizontal: Story = {};

export const Vertical: Story = {
	args: {
		direction: 'vertical'
	}
};
