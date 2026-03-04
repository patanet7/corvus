import type { Meta, StoryObj } from '@storybook/sveltekit';
import PromptInspectorPanel from './PromptInspectorPanel.svelte';

const meta = {
	title: 'Agents/Cards/PromptInspector',
	component: PromptInspectorPanel,
	tags: ['autodocs'],
	args: {
		preview: {
			agent: 'huginn',
			safeMode: true,
			totalLayers: 4,
			totalChars: 3412,
			fullPreview:
				'You are an agent in Corvus.\n\n---\n\nYou are the huginn agent.\n\n---\n\n# Huginn Instructions\nRoute intelligently.\n\n---\n\n[redacted in safe preview]',
			fullPreviewClipped: true,
			layers: [
				{
					id: 'soul',
					title: 'Soul',
					source: 'corvus/prompts/soul.md',
					charCount: 934,
					clipped: false,
					contentPreview: 'You are an agent in Corvus...'
				},
				{
					id: 'agent_identity',
					title: 'Agent Identity',
					source: 'generated',
					charCount: 112,
					clipped: false,
					contentPreview: 'You are the **huginn** agent...'
				},
				{
					id: 'agent_prompt',
					title: 'Agent Prompt',
					source: 'corvus/prompts/huginn.md',
					charCount: 2231,
					clipped: true,
					contentPreview: '# Huginn Instructions\nRoute intelligently...'
				},
				{
					id: 'user_profile',
					title: 'User Profile',
					source: '/workspace/USER.md',
					charCount: 28,
					clipped: false,
					contentPreview: '[redacted in safe preview]'
				}
			]
		}
	}
} satisfies Meta<typeof PromptInspectorPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SafePreview: Story = {};

export const Loading: Story = {
	args: {
		loading: true,
		preview: null
	}
};

export const ErrorState: Story = {
	args: {
		error: 'Failed to load prompt preview.',
		preview: null
	}
};
