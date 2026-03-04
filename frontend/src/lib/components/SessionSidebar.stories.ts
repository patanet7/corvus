import type { Meta, StoryObj } from '@storybook/sveltekit';
import SessionSidebar from './SessionSidebar.svelte';
import type { Session } from '$lib/types';

const sessions: Session[] = [
	{
		id: 'session-1',
		user: 'user',
		name: 'Homelab ops check',
		startedAt: '2026-03-02T17:30:00Z',
		messageCount: 12,
		toolCount: 4,
		agentsUsed: ['homelab', 'general']
	},
	{
		id: 'session-2',
		user: 'user',
		name: 'Work planning',
		startedAt: '2026-03-02T16:10:00Z',
		messageCount: 8,
		toolCount: 0,
		agentsUsed: ['work']
	}
];

const meta = {
	title: 'Chat/SessionSidebar',
	component: SessionSidebar,
	tags: ['autodocs'],
	args: {
		sessions,
		activeSessionId: 'session-1',
		width: 260,
		loading: false,
		error: null,
		onSelectSession: () => {},
		onNewChat: () => {}
	}
} satisfies Meta<typeof SessionSidebar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Loading: Story = {
	args: {
		sessions: [],
		loading: true
	}
};

export const ErrorState: Story = {
	args: {
		sessions: [],
		error: 'Failed to load sessions (401)'
	}
};

