import type { Meta, StoryObj } from '@storybook/sveltekit';
import TaskSidebar from './TaskSidebar.svelte';
import { taskStore } from '$lib/stores.svelte';
import { storyTask } from './storybook-fixtures';

function seedTasks(mode: 'empty' | 'mixed'): void {
	if (mode === 'empty') {
		taskStore.tasks = new Map();
		taskStore.activeTaskId = null;
		return;
	}
	const active = storyTask({
		id: 'task-active',
		status: 'streaming',
		phase: 'executing',
		result: undefined,
		summary: 'Streaming updates from homelab agent'
	});
	const completed = storyTask({
		id: 'task-completed',
		agent: 'work',
		status: 'done',
		phase: 'done',
		result: 'success',
		summary: 'Work validation done',
		startedAt: new Date(Date.now() - 120_000),
		completedAt: new Date(Date.now() - 30_000)
	});
	taskStore.tasks = new Map([
		[active.id, active],
		[completed.id, completed]
	]);
	taskStore.activeTaskId = active.id;
}

const meta = {
	title: 'Tasks/TaskSidebar',
	component: TaskSidebar,
	tags: ['autodocs'],
	args: {
		width: 300,
		onSelectTask: () => {},
		onInterruptTask: () => {}
	}
} satisfies Meta<typeof TaskSidebar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
	render: (args) => {
		seedTasks('empty');
		return {
			Component: TaskSidebar,
			props: args
		};
	}
};

export const Mixed: Story = {
	render: (args) => {
		seedTasks('mixed');
		return {
			Component: TaskSidebar,
			props: args
		};
	}
};
