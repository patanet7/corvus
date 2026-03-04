import type { Meta, StoryObj } from '@storybook/sveltekit';
import MemoryCreateCard from './MemoryCreateCard.svelte';

const meta = {
	title: 'Workspace/MemoryCreateCard',
	component: MemoryCreateCard,
	tags: ['autodocs']
} satisfies Meta<typeof MemoryCreateCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Enabled: Story = {
	args: {
		enabled: true,
		loading: false,
		domain: 'homelab'
	}
};

export const Disabled: Story = {
	args: {
		enabled: false,
		loading: false
	}
};
