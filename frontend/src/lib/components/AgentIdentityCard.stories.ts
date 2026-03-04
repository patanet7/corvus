import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentIdentityCard from './AgentIdentityCard.svelte';

const baseAgent = {
	id: 'huginn',
	label: 'Huginn',
	description: 'Router and orchestration agent',
	runtimeStatus: 'active' as const,
	currentModel: 'sonnet',
	queueDepth: 0,
	complexity: 'high',
	toolModules: ['memory', 'obsidian'],
	memoryDomain: 'shared',
	hasPrompt: true
};

const meta = {
	title: 'Agents/Cards/Identity',
	component: AgentIdentityCard,
	tags: ['autodocs'],
	args: {
		agent: baseAgent,
		profile: {
			id: 'huginn',
			label: 'Huginn',
			description: 'Router and orchestration agent',
			enabled: true,
			promptFile: 'corvus/prompts/huginn.md',
			resolvedModel: 'sonnet',
			preferredModel: 'sonnet',
			fallbackModel: 'haiku',
			autoModelRouting: true,
			complexity: 'high',
			memoryDomain: 'shared',
			readableDomains: ['shared', 'work'],
			canReadShared: true,
			canWriteMemory: true,
			builtinTools: ['Bash'],
			confirmGatedTools: [],
			moduleConfig: { obsidian: { allowed_prefixes: null } },
			metadata: {},
			recentRuns: []
		}
	}
} satisfies Meta<typeof AgentIdentityCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Active: Story = {};

export const OfflineDegraded: Story = {
	args: {
		agent: {
			...baseAgent,
			runtimeStatus: 'offline',
			currentModel: null,
			queueDepth: 3
		},
		profile: {
			id: 'huginn',
			label: 'Huginn',
			description: 'Router and orchestration agent',
			enabled: true,
			autoModelRouting: false,
			readableDomains: [],
			canReadShared: false,
			canWriteMemory: false,
			builtinTools: [],
			confirmGatedTools: [],
			moduleConfig: {},
			metadata: {},
			recentRuns: []
		}
	}
};
