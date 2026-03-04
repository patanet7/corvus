import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentIdentityBlueprintCard from './AgentIdentityBlueprintCard.svelte';

const meta = {
	title: 'Agents/Cards/IdentityBlueprint',
	component: AgentIdentityBlueprintCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'homelab',
			label: 'Homelab',
			description: 'System operations and diagnostics',
			runtimeStatus: 'active',
			currentModel: 'claude-sonnet',
			queueDepth: 1,
			complexity: 'high',
			toolModules: ['memory', 'obsidian']
		},
		profile: {
			id: 'homelab',
			label: 'Homelab',
			description: 'System operations and diagnostics',
			enabled: true,
			autoModelRouting: true,
			readableDomains: ['homelab'],
			canReadShared: true,
			canWriteMemory: true,
			builtinTools: ['Bash', 'Read'],
			confirmGatedTools: ['obsidian.write'],
			moduleConfig: { memory: { enabled: true } },
			metadata: { persona: 'Calm tactical operator' },
			recentRuns: []
		}
	}
} satisfies Meta<typeof AgentIdentityBlueprintCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
