import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentPermissionsMatrixCard from './AgentPermissionsMatrixCard.svelte';

const meta = {
	title: 'Agents/Cards/PermissionsMatrix',
	component: AgentPermissionsMatrixCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'home',
			label: 'Home',
			runtimeStatus: 'active'
		},
		policy: {
			agent: 'home',
			runtime: {
				permissionMode: 'default'
			},
			summary: {
				total: 4,
				allow: 2,
				confirm: 1,
				deny: 1
			},
			entries: [
				{
					key: 'builtin:Bash',
					scope: 'builtin_tool',
					subject: 'Bash',
					state: 'allow',
					reason: 'Declared in agent tools.builtin.'
				},
				{
					key: 'module:ha',
					scope: 'module_access',
					subject: 'ha',
					state: 'allow',
					reason: 'Capability module resolved and environment gates passed.'
				},
				{
					key: 'confirm:ha.call_service',
					scope: 'tool_confirmation',
					subject: 'ha.call_service',
					state: 'confirm',
					reason: 'Requires explicit user confirmation before execution.'
				},
				{
					key: 'module:paperless',
					scope: 'module_access',
					subject: 'paperless',
					state: 'deny',
					reason: 'Capability module denied: unregistered or missing required environment.'
				}
			]
		}
	}
} satisfies Meta<typeof AgentPermissionsMatrixCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {};

export const Loading: Story = {
	args: {
		loading: true,
		policy: null
	}
};

export const ErrorState: Story = {
	args: {
		error: 'Failed to load policy matrix.',
		policy: null
	}
};
