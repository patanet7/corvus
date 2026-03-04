import type { Meta, StoryObj } from '@storybook/sveltekit';
import TaskRunCard from './TaskRunCard.svelte';

const meta = {
	title: 'Tasks/TaskRunCard',
	component: TaskRunCard,
	tags: ['autodocs'],
	args: {
		variant: 'log-stream',
		title: 'Docker Log Analysis',
		agent: 'homelab',
		model: 'claude-sonnet',
		status: 'running',
		elapsedLabel: '02:14',
		summary: 'Parsing and classifying runtime logs',
		logLines: ['[INFO] tailing 500 lines', '[WARN] timeout on 192.168.1.45']
	}
} satisfies Meta<typeof TaskRunCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LogStream: Story = {};

export const Progress: Story = {
	args: {
		variant: 'progress',
		progressPct: 38
	}
};

export const DiffPreview: Story = {
	args: {
		variant: 'diff-preview',
		status: 'done',
		diffLines: ['@@ src/components/Nav.svelte @@', '- const active = false;', '+ const active = $state(false);']
	}
};
