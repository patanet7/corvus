import type { Meta, StoryObj } from '@storybook/sveltekit';
import MemoryPanel from './MemoryPanel.svelte';

const meta = {
	title: 'Workspace/MemoryPanel',
	component: MemoryPanel,
	tags: ['autodocs']
} satisfies Meta<typeof MemoryPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const BackendDisabled: Story = {
	args: {
		backendDisabled: true
	}
};
