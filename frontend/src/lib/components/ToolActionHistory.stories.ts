import type { Meta, StoryObj } from '@storybook/sveltekit';
import ToolActionHistory from './ToolActionHistory.svelte';

const sampleEvents = [
	{
		id: 1,
		run_id: 'run_alpha_1234',
		dispatch_id: 'dispatch_alpha',
		session_id: 'session_alpha',
		turn_id: 'turn_alpha',
		event_type: 'tool_start',
		payload: { tool: 'Bash', call_id: 'call_01', params: { command: 'ls -la' } },
		created_at: '2026-03-04T10:00:01Z'
	},
	{
		id: 2,
		run_id: 'run_alpha_1234',
		dispatch_id: 'dispatch_alpha',
		session_id: 'session_alpha',
		turn_id: 'turn_alpha',
		event_type: 'tool_result',
		payload: { tool: 'Bash', call_id: 'call_01', status: 'success', output: 'total 8\n-rw-r--r-- file.txt' },
		created_at: '2026-03-04T10:00:02Z'
	},
	{
		id: 3,
		run_id: 'run_alpha_1234',
		dispatch_id: 'dispatch_alpha',
		session_id: 'session_alpha',
		turn_id: 'turn_alpha',
		event_type: 'confirm_request',
		payload: { tool: 'mcp__email__email_send', call_id: 'call_02', timeout_s: 60 },
		created_at: '2026-03-04T10:00:03Z'
	},
	{
		id: 4,
		run_id: 'run_alpha_1234',
		dispatch_id: 'dispatch_alpha',
		session_id: 'session_alpha',
		turn_id: 'turn_alpha',
		event_type: 'confirm_response',
		payload: { tool: 'mcp__email__email_send', call_id: 'call_02', approved: false },
		created_at: '2026-03-04T10:00:04Z'
	},
	{
		id: 5,
		run_id: 'run_alpha_1234',
		dispatch_id: 'dispatch_alpha',
		session_id: 'session_alpha',
		turn_id: 'turn_alpha',
		event_type: 'tool_result',
		payload: { tool: 'mcp__email__email_send', call_id: 'call_02', status: 'error', output: 'Permission denied' },
		created_at: '2026-03-04T10:00:05Z'
	}
];

const meta = {
	title: 'Agents/History/ToolActionHistory',
	component: ToolActionHistory,
	tags: ['autodocs'],
	args: {
		events: sampleEvents
	}
} satisfies Meta<typeof ToolActionHistory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Loading: Story = {
	args: {
		events: [],
		loading: true
	}
};

export const Error: Story = {
	args: {
		events: [],
		error: 'Failed to load tool actions.'
	}
};

export const Empty: Story = {
	args: {
		events: []
	}
};
