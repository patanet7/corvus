import type { Meta, StoryObj } from '@storybook/sveltekit';
import ThemeSelector from './ThemeSelector.svelte';

const meta = {
	title: 'Config/ThemeSelector',
	component: ThemeSelector,
	tags: ['autodocs']
} satisfies Meta<typeof ThemeSelector>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
