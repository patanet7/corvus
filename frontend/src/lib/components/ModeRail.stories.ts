import type { Meta, StoryObj } from '@storybook/sveltekit';
import ModeRail from './ModeRail.svelte';

const meta = {
	title: 'Layout/ModeRail',
	component: ModeRail,
	tags: ['autodocs'],
	args: {
		activeMode: 'chat',
		onModeChange: () => {}
	}
} satisfies Meta<typeof ModeRail>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Chat: Story = {};

export const Tasks: Story = {
	args: {
		activeMode: 'tasks'
	}
};

export const Timeline: Story = {
	args: {
		activeMode: 'timeline'
	}
};

export const Memory: Story = {
	args: {
		activeMode: 'memory'
	}
};
