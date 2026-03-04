import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentPromptIdentityCard from './AgentPromptIdentityCard.svelte';

const meta = {
	title: 'Agents/Cards/PromptIdentity',
	component: AgentPromptIdentityCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'work',
			label: 'Work',
			description: 'Work execution agent',
			runtimeStatus: 'active',
			currentModel: 'sonnet',
			hasPrompt: true
		},
		profile: {
			id: 'work',
			label: 'Work',
			description: 'Work execution agent',
			enabled: true,
			promptFile: 'corvus/prompts/work.md',
			resolvedModel: 'sonnet',
			preferredModel: 'sonnet',
			fallbackModel: 'haiku',
			autoModelRouting: true,
			readableDomains: ['work'],
			canReadShared: true,
			canWriteMemory: true,
			builtinTools: ['Bash'],
			confirmGatedTools: [],
			moduleConfig: {},
			metadata: {},
			recentRuns: []
		}
	}
} satisfies Meta<typeof AgentPromptIdentityCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ConfiguredPrompt: Story = {};

export const MissingPromptFile: Story = {
	args: {
		agent: {
			id: 'general',
			label: 'General',
			description: 'Fallback generalist',
			runtimeStatus: 'active',
			currentModel: 'haiku',
			hasPrompt: false
		},
		profile: {
			id: 'general',
			label: 'General',
			description: 'Fallback generalist',
			enabled: true,
			autoModelRouting: false,
			readableDomains: [],
			canReadShared: true,
			canWriteMemory: false,
			builtinTools: [],
			confirmGatedTools: [],
			moduleConfig: {},
			metadata: {},
			recentRuns: []
		}
	}
};
