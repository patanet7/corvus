import type { Meta, StoryObj } from '@storybook/sveltekit';
import SessionListItem from './SessionListItem.svelte';
import { storySession } from './storybook-fixtures';

const meta = {
	title: 'Chat/SessionListItem',
	component: SessionListItem,
	tags: ['autodocs'],
	args: {
		session: storySession,
		active: false,
		onSelect: () => {},
		onRename: () => {},
		onDelete: () => {}
	}
} satisfies Meta<typeof SessionListItem>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Active: Story = {
	args: {
		active: true
	}
};
