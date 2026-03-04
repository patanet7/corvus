import type { Meta, StoryObj } from '@storybook/sveltekit';
import ValidationRail from './ValidationRail.svelte';

const meta = {
	title: 'Agents/ValidationRail',
	component: ValidationRail,
	tags: ['autodocs'],
	args: {
		metrics: {
			totalRuns: 142,
			errorRatePct: 0.4,
			avgCostUsd: 0.02,
			uptimePct: 99.9
		},
		dependencies: [
			{ id: '/usr/bin/kubectl', status: 'ok' },
			{ id: '/usr/bin/python3', status: 'ok' },
			{ id: '/usr/local/bin/aws', status: 'missing', detail: 'CLI missing in local env' }
		],
		quotas: [
			{ id: 'context', label: 'Context Window', used: 56, limit: 100 },
			{ id: 'tool_calls', label: 'Tool Calls', used: 12, limit: 40 }
		],
		auditRows: [
			{ id: 'a1', timestamp: '14:32:10', message: 'Policy reload applied', severity: 'info' },
			{ id: 'a2', timestamp: '14:31:48', message: 'Module obsidian degraded', severity: 'warning' }
		]
	}
} satisfies Meta<typeof ValidationRail>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
