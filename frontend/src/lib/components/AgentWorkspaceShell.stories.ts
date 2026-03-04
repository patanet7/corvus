import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentWorkspaceShell from './AgentWorkspaceShell.svelte';

const meta = {
	title: 'Agents/AgentWorkspaceShell',
	component: AgentWorkspaceShell,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'homelab',
			label: 'Homelab',
			description: 'Infrastructure and service management',
			runtimeStatus: 'busy',
			currentModel: 'ollama/qwen3:8b',
			queueDepth: 2,
			toolModules: ['ha', 'paperless'],
			memoryDomain: 'homelab',
			hasPrompt: true
		},
		agentProfile: {
			id: 'homelab',
			label: 'Homelab',
			description: 'Infrastructure and service management',
			enabled: true,
			promptFile: 'corvus/prompts/homelab.md',
			resolvedModel: 'ollama/qwen3:8b',
			preferredModel: 'ollama/qwen3:8b',
			fallbackModel: 'haiku',
			autoModelRouting: true,
			complexity: 'high',
			memoryDomain: 'homelab',
			readableDomains: ['homelab', 'shared'],
			canReadShared: true,
			canWriteMemory: true,
			builtinTools: ['Bash'],
			confirmGatedTools: ['ha.call_service'],
			moduleConfig: { ha: {}, paperless: {} },
			metadata: {},
			recentRuns: []
		},
		moduleHealthByName: {
			ha: { name: 'ha', status: 'healthy', message: 'Connected' },
			paperless: { name: 'paperless', status: 'degraded', message: 'Auth expires soon' }
		},
		promptPreview: {
			agent: 'homelab',
			safeMode: true,
			totalLayers: 4,
			totalChars: 2100,
			fullPreview: 'Safe prompt preview...',
			fullPreviewClipped: false,
			layers: [
				{
					id: 'soul',
					title: 'Soul',
					source: 'corvus/prompts/soul.md',
					charCount: 600,
					clipped: false,
					contentPreview: 'You are Corvus...'
				}
			]
		},
		agentPolicy: {
			agent: 'homelab',
			runtime: { permissionMode: 'default' },
			summary: { total: 3, allow: 1, confirm: 1, deny: 1 },
			entries: [
				{
					key: 'builtin:Bash',
					scope: 'builtin_tool',
					subject: 'Bash',
					state: 'allow',
					reason: 'Declared in agent tools.builtin.'
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
		},
		agentTodos: {
			agent: 'homelab',
			scope: 'per_agent',
			totals: { files: 1, items: 3, pending: 1, inProgress: 1, completed: 1, other: 0 },
			files: [
				{
					id: 'sess-001-agent-aaaa',
					sessionId: 'sess-001',
					updatedAt: '2026-03-03T16:12:00Z',
					itemCount: 3,
					summary: { pending: 1, inProgress: 1, completed: 1, other: 0 },
					items: [
						{
							id: 'sess-001-agent-aaaa:0',
							content: 'Check Plex container status',
							status: 'completed'
						},
						{
							id: 'sess-001-agent-aaaa:1',
							content: 'Review nginx 502 logs',
							status: 'in_progress',
							activeForm: 'Reviewing nginx 502 logs'
						},
						{
							id: 'sess-001-agent-aaaa:2',
							content: 'Draft follow-up remediation plan',
							status: 'pending'
						}
					]
				}
			]
		},
		tab: 'chat',
		sessions: [
			{
				id: 'sess-001',
				user: 'user',
				name: 'Plex restart check',
				startedAt: '2026-03-03T16:10:00Z',
				messageCount: 12,
				toolCount: 5,
				agentsUsed: ['homelab']
			}
		],
		runs: [
			{
				id: 'run-001',
				dispatch_id: 'disp-001',
				session_id: 'sess-001',
				agent: 'homelab',
				status: 'done',
				summary: 'Validated Plex and restarted unhealthy containers.',
				cost_usd: 0.03,
				tokens_used: 1800,
				context_limit: 32768,
				context_pct: 5.5,
				started_at: '2026-03-03T16:11:00Z',
				completed_at: '2026-03-03T16:11:10Z'
			}
		],
		selectedRunId: 'run-001',
		runEvents: [
			{
				id: 1,
				run_id: 'run-001',
				dispatch_id: 'disp-001',
				session_id: 'sess-001',
				event_type: 'run_phase',
				payload: { phase: 'executing', summary: 'Collecting logs' },
				created_at: '2026-03-03T16:11:02Z'
			},
			{
				id: 2,
				run_id: 'run-001',
				dispatch_id: 'disp-001',
				session_id: 'sess-001',
				event_type: 'run_output_chunk',
				payload: { chunk_index: 0, content: '[INFO] Checking docker logs', final: false },
				created_at: '2026-03-03T16:11:03Z'
			},
			{
				id: 3,
				run_id: 'run-001',
				dispatch_id: 'disp-001',
				session_id: 'sess-001',
				event_type: 'run_phase',
				payload: { phase: 'compacting', summary: 'Compacting response' },
				created_at: '2026-03-03T16:11:08Z'
			}
		],
		runEventsLoading: false,
		runEventsError: null,
		onTabChange: () => {},
		onSelectSession: () => {},
		onSelectRun: () => {},
		onPinAgent: () => {}
	}
} satisfies Meta<typeof AgentWorkspaceShell>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ChatTab: Story = {};

export const TasksTab: Story = {
	args: {
		tab: 'tasks'
	}
};

export const ConfigTab: Story = {
	args: {
		tab: 'config'
	}
};

export const ValidationTab: Story = {
	args: {
		tab: 'validation',
		runs: [
			{
				id: 'run-err',
				dispatch_id: 'disp-err',
				session_id: 'sess-err',
				agent: 'homelab',
				status: 'error',
				summary: 'Timed out contacting backend',
				cost_usd: 0,
				tokens_used: 0,
				context_limit: 32768,
				context_pct: 0,
				error: 'timeout',
				started_at: '2026-03-03T18:00:00Z'
			}
		]
	}
};
