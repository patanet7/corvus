import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentToolsPermissionsCard from './AgentToolsPermissionsCard.svelte';

const meta = {
	title: 'Agents/Cards/ToolsPermissions',
	component: AgentToolsPermissionsCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'email',
			label: 'Email',
			runtimeStatus: 'active',
			toolModules: ['email', 'drive']
		},
		profile: {
			id: 'email',
			label: 'Email',
			description: 'Mailbox triage',
			enabled: true,
			autoModelRouting: true,
			readableDomains: ['email'],
			canReadShared: true,
			canWriteMemory: true,
			builtinTools: ['Bash', 'Read'],
			confirmGatedTools: ['email.send', 'drive.share'],
			moduleConfig: {
				email: {},
				drive: {}
			},
			metadata: {},
			recentRuns: []
		}
	}
} satisfies Meta<typeof AgentToolsPermissionsCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithConfirmGates: Story = {};

export const Minimal: Story = {
	args: {
		agent: {
			id: 'docs',
			label: 'Docs',
			runtimeStatus: 'active',
			toolModules: []
		},
		profile: {
			id: 'docs',
			label: 'Docs',
			description: 'Docs assistant',
			enabled: true,
			autoModelRouting: true,
			readableDomains: ['docs'],
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
