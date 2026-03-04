import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentModelRoutingCard from './AgentModelRoutingCard.svelte';

const meta = {
	title: 'Agents/Cards/ModelRouting',
	component: AgentModelRoutingCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'huginn',
			label: 'Huginn',
			description: 'Router agent',
			runtimeStatus: 'active'
		},
		lanes: [
			{
				id: 'reason',
				label: 'Reasoning Core',
				purpose: 'Long context planning tasks',
				model: 'claude-3-7-sonnet',
				fallbacks: ['gpt-4.1'],
				status: 'healthy'
			},
			{
				id: 'code',
				label: 'Code Synthesis',
				purpose: 'Patch authoring and refactors',
				model: 'claude-3-7-sonnet',
				fallbacks: ['qwen2.5-coder'],
				status: 'healthy'
			},
			{
				id: 'rapid',
				label: 'Rapid Response',
				purpose: 'Quick turn chat',
				model: 'haiku',
				fallbacks: ['claude-3-7-sonnet'],
				status: 'degraded'
			}
		]
	}
} satisfies Meta<typeof AgentModelRoutingCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
