import type { Meta, StoryObj } from '@storybook/sveltekit';
import TraceTimelinePanel from './TraceTimelinePanel.svelte';

const meta = {
	title: 'Timeline/TraceTimelinePanel',
	component: TraceTimelinePanel,
	tags: ['autodocs'],
	args: {
		sessionId: null,
		backendDisabled: true
	}
} satisfies Meta<typeof TraceTimelinePanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const BackendDisabled: Story = {};

export const SessionScopedDisabled: Story = {
	args: {
		sessionId: 'session-1',
		backendDisabled: true
	}
};
