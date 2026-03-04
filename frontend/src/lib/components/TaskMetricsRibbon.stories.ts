import type { Meta, StoryObj } from '@storybook/sveltekit';
import TaskMetricsRibbon from './TaskMetricsRibbon.svelte';

const meta = {
	title: 'Tasks/TaskMetricsRibbon',
	component: TaskMetricsRibbon,
	tags: ['autodocs'],
	args: {
		metrics: [
			{ id: 'active', label: 'Active Agents', value: 3, tone: 'info' },
			{ id: 'cost', label: 'Session Spend', value: '$0.42' },
			{ id: 'tokens', label: 'Tokens', value: '12.4k', hint: 'Current session' },
			{ id: 'context', label: 'Context', value: '65%', tone: 'warning' }
		]
	}
} satisfies Meta<typeof TaskMetricsRibbon>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
