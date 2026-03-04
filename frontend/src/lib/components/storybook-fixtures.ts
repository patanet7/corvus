import type { AgentInfo, ChatMessage, ConfirmRequest, ModelInfo, Session, Task } from '$lib/types';

export const storyModels: ModelInfo[] = [
	{
		id: 'ollama/llama3:8b',
		label: 'llama3:8b',
		backend: 'ollama',
		available: true,
		description: 'Local Ollama chat model',
		isDefault: true,
		capabilities: { supports_tools: false, supports_streaming: true }
	},
	{
		id: 'claude/sonnet-4-5',
		label: 'Claude Sonnet 4.5',
		backend: 'claude',
		available: true,
		description: 'High-reasoning fallback',
		capabilities: { supports_tools: true, supports_streaming: true }
	},
	{
		id: 'ollama/gpt-oss:20b',
		label: 'gpt-oss:20b',
		backend: 'ollama',
		available: false,
		description: 'Offline fixture',
		capabilities: { supports_tools: false, supports_streaming: true }
	}
];

export const storyAgents: AgentInfo[] = [
	{
		id: 'general',
		label: 'General',
		isDefault: true,
		runtimeStatus: 'active',
		currentModel: 'ollama/llama3:8b',
		complexity: 'medium',
		toolModules: ['sessions', 'routing'],
		memoryDomain: 'shared',
		hasPrompt: true
	},
	{
		id: 'work',
		label: 'Work',
		runtimeStatus: 'busy',
		currentModel: 'claude/sonnet-4-5',
		complexity: 'high',
		toolModules: ['github', 'calendar'],
		memoryDomain: 'work',
		hasPrompt: true
	},
	{
		id: 'homelab',
		label: 'Homelab',
		runtimeStatus: 'active',
		currentModel: 'ollama/llama3:8b',
		complexity: 'high',
		toolModules: ['docker', 'monitoring'],
		memoryDomain: 'ops',
		hasPrompt: true
	}
];

export const storyMessages: ChatMessage[] = [
	{
		id: 'msg-user-1',
		role: 'user',
		content: '@homelab check plex status',
		timestamp: new Date('2026-03-03T17:00:00Z')
	},
	{
		id: 'msg-assistant-1',
		role: 'assistant',
		content: 'Plex is running and healthy.',
		agent: 'homelab',
		model: 'ollama/llama3:8b',
		timestamp: new Date('2026-03-03T17:00:03Z'),
		runtimeEvents: [
			{
				id: 'rt-1',
				kind: 'thinking',
				summary: 'planning: checking active containers',
				timestamp: new Date('2026-03-03T17:00:01Z')
			},
			{
				id: 'rt-2',
				kind: 'tool_start',
				summary: 'Tool started: docker.ps',
				timestamp: new Date('2026-03-03T17:00:02Z'),
				callId: 'call-001'
			},
			{
				id: 'rt-3',
				kind: 'tool_result',
				summary: 'Tool success: docker.ps',
				timestamp: new Date('2026-03-03T17:00:02.500Z'),
				callId: 'call-001',
				detail: 'plex is healthy'
			}
		]
	}
];

export const storyConfirmRequest: ConfirmRequest = {
	callId: 'confirm-1',
	tool: 'file.write',
	params: { path: 'notes/today.md', overwrite: false },
	timeoutS: 30,
	createdAt: new Date()
};

export function storyTask(overrides?: Partial<Task>): Task {
	return {
		id: 'task-1',
		agent: 'homelab',
		dispatchId: 'dispatch-1',
		runId: 'run-1',
		description: 'Check homelab service health',
		status: 'streaming',
		phase: 'executing',
		summary: 'Streaming response from agent',
		result: undefined,
		costUsd: 0.07,
		startedAt: new Date(Date.now() - 20_000),
		completedAt: undefined,
		messages: [],
		sessionId: 'session-1',
		turnId: 'turn-1',
		events: [
			{
				kind: 'run_phase',
				timestamp: new Date(Date.now() - 15_000),
				text: 'executing: calling docker ps'
			},
			{
				kind: 'run_output_chunk',
				timestamp: new Date(Date.now() - 6_000),
				text: 'Plex container is healthy.'
			}
		],
		...overrides
	};
}

export const storySession: Session = {
	id: 'session-1',
	user: 'user',
	name: 'Chat session',
	startedAt: new Date(Date.now() - 60_000).toISOString(),
	endedAt: undefined,
	messageCount: 2,
	toolCount: 1,
	agentsUsed: ['general', 'homelab']
};
