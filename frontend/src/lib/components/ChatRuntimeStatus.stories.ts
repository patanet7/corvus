import type { Meta, StoryObj } from '@storybook/sveltekit';
import ChatRuntimeStatus from './ChatRuntimeStatus.svelte';
import type { Task } from '$lib/types';

const runtimeTask: Task = {
	id: 'task-ops-1',
	agent: 'homelab',
	description: 'Investigate service restart',
	status: 'streaming',
	phase: 'executing',
	summary: 'Running checks and collecting logs',
	costUsd: 0.04,
	startedAt: new Date('2026-03-03T13:20:00Z'),
	messages: [],
	events: [
		{
			kind: 'run_phase',
			timestamp: new Date('2026-03-03T13:20:01Z'),
			text: 'planning: gather target host and service details'
		},
		{
			kind: 'tool_start',
			timestamp: new Date('2026-03-03T13:20:03Z'),
			text: 'Tool started: tailscale_status',
			callId: 'call-aaa'
		},
		{
			kind: 'tool_result',
			timestamp: new Date('2026-03-03T13:20:05Z'),
			text: 'Tool success: call-aaa',
			callId: 'call-aaa'
		}
	]
};

const meta = {
	title: 'Chat/ChatRuntimeStatus',
	component: ChatRuntimeStatus,
	tags: ['autodocs'],
	args: {
		agentStatus: 'thinking',
		runtimeTask,
		onOpenTrace: () => {}
	}
} satisfies Meta<typeof ChatRuntimeStatus>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Thinking: Story = {};

export const Streaming: Story = {
	args: {
		agentStatus: 'streaming'
	}
};

export const HiddenWhenIdle: Story = {
	args: {
		agentStatus: 'idle',
		runtimeTask: null
	}
};
