import type { Meta, StoryObj } from '@storybook/sveltekit';
import TaskDetailPanel from './TaskDetailPanel.svelte';
import { storyTask } from './storybook-fixtures';

const meta = {
	title: 'Tasks/TaskDetailPanel',
	component: TaskDetailPanel,
	tags: ['autodocs'],
	args: {
		task: storyTask(),
		traceCallId: null,
		onInterrupt: () => {},
		onClearTraceFocus: () => {}
	}
} satisfies Meta<typeof TaskDetailPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Active: Story = {};

export const Completed: Story = {
	args: {
		task: storyTask({
			status: 'done',
			phase: 'done',
			result: 'success',
			summary: 'Validation completed successfully.',
			completedAt: new Date()
		})
	}
};

export const Empty: Story = {
	args: {
		task: null
	}
};
