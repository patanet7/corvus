import type { Meta, StoryObj } from '@storybook/sveltekit';
import TaskFilterBar from './TaskFilterBar.svelte';

const meta = {
	title: 'Tasks/TaskFilterBar',
	component: TaskFilterBar,
	tags: ['autodocs'],
	args: {
		search: 'docker',
		statusOptions: ['running', 'done', 'error'],
		selectedStatuses: ['running'],
		agentOptions: ['homelab', 'work', 'finance'],
		selectedAgents: ['homelab'],
		onSearchChange: () => {},
		onStatusToggle: () => {},
		onAgentToggle: () => {},
		onClear: () => {}
	}
} satisfies Meta<typeof TaskFilterBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
