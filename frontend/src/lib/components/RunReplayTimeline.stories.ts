import type { Meta, StoryObj } from '@storybook/sveltekit';
import RunReplayTimeline from './RunReplayTimeline.svelte';

const meta = {
	title: 'Agents/RunReplayTimeline',
	component: RunReplayTimeline,
	tags: ['autodocs'],
	args: {
		events: [
			{
				id: 11,
				run_id: 'run-11',
				dispatch_id: 'disp-11',
				session_id: 'sess-11',
				event_type: 'run_phase',
				payload: { phase: 'executing', summary: 'Gathering tool output' },
				created_at: '2026-03-03T11:11:01Z'
			},
			{
				id: 12,
				run_id: 'run-11',
				dispatch_id: 'disp-11',
				session_id: 'sess-11',
				event_type: 'run_output_chunk',
				payload: { chunk_index: 0, content: 'Starting analysis...', final: false },
				created_at: '2026-03-03T11:11:02Z'
			},
			{
				id: 13,
				run_id: 'run-11',
				dispatch_id: 'disp-11',
				session_id: 'sess-11',
				event_type: 'tool_result',
				payload: { status: 'success', call_id: 'tool-123' },
				created_at: '2026-03-03T11:11:03Z'
			},
			{
				id: 14,
				run_id: 'run-11',
				dispatch_id: 'disp-11',
				session_id: 'sess-11',
				event_type: 'run_output_chunk',
				payload: { chunk_index: 4, content: '', final: true },
				created_at: '2026-03-03T11:11:07Z'
			}
		]
	}
} satisfies Meta<typeof RunReplayTimeline>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Loading: Story = {
	args: {
		events: [],
		loading: true
	}
};

export const ErrorState: Story = {
	args: {
		events: [],
		error: 'Failed to load replay events.'
	}
};
