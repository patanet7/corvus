import { describe, it, expect } from 'vitest';
import {
	AGENT_NAMES,
	isValidAgentName
} from './types';
import type {
	ModelInfo,
	AgentInfo,
	ChatMessage,
	ChatRuntimeEvent,
	ToolCall,
	ConfirmRequest,
	Session,
	Task,
	ClientMessage,
	ServerMessage,
	AgentStatus,
	ConnectionStatus,
	AgentName
} from './types';

describe('AGENT_NAMES constant', () => {
	it('contains exactly 10 entries', () => {
		expect(AGENT_NAMES).toHaveLength(10);
	});

	it('contains personal', () => {
		expect(AGENT_NAMES).toContain('personal');
	});

	it('contains work', () => {
		expect(AGENT_NAMES).toContain('work');
	});

	it('contains homelab', () => {
		expect(AGENT_NAMES).toContain('homelab');
	});

	it('contains finance', () => {
		expect(AGENT_NAMES).toContain('finance');
	});

	it('contains email', () => {
		expect(AGENT_NAMES).toContain('email');
	});

	it('contains docs', () => {
		expect(AGENT_NAMES).toContain('docs');
	});

	it('contains music', () => {
		expect(AGENT_NAMES).toContain('music');
	});

	it('contains home', () => {
		expect(AGENT_NAMES).toContain('home');
	});

	it('contains huginn', () => {
		expect(AGENT_NAMES).toContain('huginn');
	});

	it('contains general', () => {
		expect(AGENT_NAMES).toContain('general');
	});

	it('is an array', () => {
		expect(Array.isArray(AGENT_NAMES)).toBe(true);
	});
});

describe('isValidAgentName', () => {
	it('returns true for every entry in AGENT_NAMES', () => {
		for (const name of AGENT_NAMES) {
			expect(isValidAgentName(name)).toBe(true);
		}
	});

	it('returns false for empty string', () => {
		expect(isValidAgentName('')).toBe(false);
	});

	it('returns false for unknown agent name', () => {
		expect(isValidAgentName('unknown')).toBe(false);
	});

	it('returns false for uppercase variant', () => {
		expect(isValidAgentName('HOMELAB')).toBe(false);
	});

	it('returns false for mixed case variant', () => {
		expect(isValidAgentName('Homelab')).toBe(false);
	});

	it('returns false for name with trailing space', () => {
		expect(isValidAgentName('homelab ')).toBe(false);
	});

	it('returns false for name with leading space', () => {
		expect(isValidAgentName(' homelab')).toBe(false);
	});

	it('returns false for numeric string', () => {
		expect(isValidAgentName('123')).toBe(false);
	});

	it('returns false for null-like strings', () => {
		expect(isValidAgentName('null')).toBe(false);
		expect(isValidAgentName('undefined')).toBe(false);
	});
});

describe('ModelInfo interface', () => {
	it('accepts minimal required fields', () => {
		const model: ModelInfo = {
			id: 'claude-sonnet-4-6',
			label: 'Claude Sonnet',
			backend: 'claude',
			available: true
		};
		expect(model.id).toBe('claude-sonnet-4-6');
		expect(model.label).toBe('Claude Sonnet');
		expect(model.description).toBeUndefined();
		expect(model.isDefault).toBeUndefined();
	});

	it('accepts all optional fields', () => {
		const model: ModelInfo = {
			id: 'claude-opus-4-6',
			label: 'Claude Opus',
			backend: 'claude',
			available: true,
			description: 'Most capable model',
			isDefault: true,
			capabilities: {
				supports_tools: true,
				supports_streaming: true
			}
		};
		expect(model.description).toBe('Most capable model');
		expect(model.isDefault).toBe(true);
		expect(model.capabilities?.supports_tools).toBe(true);
	});

	it('isDefault can be false', () => {
		const model: ModelInfo = {
			id: 'claude-haiku-35',
			label: 'Claude Haiku',
			backend: 'claude',
			available: true,
			isDefault: false
		};
		expect(model.isDefault).toBe(false);
	});
});

describe('AgentInfo interface', () => {
	it('accepts minimal required fields', () => {
		const agent: AgentInfo = {
			id: 'homelab',
			label: 'Homelab'
		};
		expect(agent.id).toBe('homelab');
		expect(agent.label).toBe('Homelab');
		expect(agent.description).toBeUndefined();
		expect(agent.isDefault).toBeUndefined();
	});

	it('accepts all optional fields', () => {
		const agent: AgentInfo = {
			id: 'general',
			label: 'General',
			description: 'General-purpose assistant',
			isDefault: true
		};
		expect(agent.description).toBe('General-purpose assistant');
		expect(agent.isDefault).toBe(true);
	});

	it('isDefault can be false', () => {
		const agent: AgentInfo = {
			id: 'finance',
			label: 'Finance',
			isDefault: false
		};
		expect(agent.isDefault).toBe(false);
	});
});

describe('ChatMessage interface', () => {
	it('accepts user role with required fields', () => {
		const msg: ChatMessage = {
			id: 'msg-001',
			role: 'user',
			content: 'Hello',
			timestamp: new Date()
		};
		expect(msg.role).toBe('user');
		expect(msg.agent).toBeUndefined();
		expect(msg.model).toBeUndefined();
		expect(msg.toolCalls).toBeUndefined();
		expect(msg.confirmRequest).toBeUndefined();
		expect(msg.isError).toBeUndefined();
	});

	it('accepts assistant role with agent and model', () => {
		const msg: ChatMessage = {
			id: 'msg-002',
			role: 'assistant',
			content: 'Running docker ps...',
			agent: 'homelab',
			model: 'claude-sonnet-4-6',
			timestamp: new Date()
		};
		expect(msg.role).toBe('assistant');
		expect(msg.agent).toBe('homelab');
		expect(msg.model).toBe('claude-sonnet-4-6');
	});

	it('accepts toolCalls array', () => {
		const toolCall: ToolCall = {
			callId: 'tc-001',
			tool: 'bash',
			params: { command: 'docker ps' },
			status: 'running'
		};
		const msg: ChatMessage = {
			id: 'msg-003',
			role: 'assistant',
			content: '',
			timestamp: new Date(),
			toolCalls: [toolCall]
		};
		expect(msg.toolCalls).toHaveLength(1);
		expect(msg.toolCalls![0].tool).toBe('bash');
	});

	it('accepts isError flag', () => {
		const msg: ChatMessage = {
			id: 'msg-004',
			role: 'assistant',
			content: 'Something went wrong',
			timestamp: new Date(),
			isError: true
		};
		expect(msg.isError).toBe(true);
	});

	it('accepts runtimeEvents timeline', () => {
		const runtimeEvent: ChatRuntimeEvent = {
			id: 'evt-001',
			kind: 'thinking',
			summary: 'Planning the next tool call',
			timestamp: new Date()
		};
		const msg: ChatMessage = {
			id: 'msg-005',
			role: 'assistant',
			content: 'I checked the logs.',
			timestamp: new Date(),
			runtimeEvents: [runtimeEvent]
		};
		expect(msg.runtimeEvents).toHaveLength(1);
		expect(msg.runtimeEvents![0].kind).toBe('thinking');
	});
});

describe('ToolCall interface', () => {
	it('accepts running status with minimal fields', () => {
		const tc: ToolCall = {
			callId: 'tc-100',
			tool: 'bash',
			params: { command: 'ls' },
			status: 'running'
		};
		expect(tc.status).toBe('running');
		expect(tc.output).toBeUndefined();
		expect(tc.durationMs).toBeUndefined();
	});

	it('accepts success status with output and duration', () => {
		const tc: ToolCall = {
			callId: 'tc-101',
			tool: 'file_read',
			params: { path: '/etc/hostname' },
			output: 'laptop-server',
			durationMs: 50,
			status: 'success'
		};
		expect(tc.status).toBe('success');
		expect(tc.output).toBe('laptop-server');
		expect(tc.durationMs).toBe(50);
	});

	it('accepts error status', () => {
		const tc: ToolCall = {
			callId: 'tc-102',
			tool: 'bash',
			params: { command: 'invalid-cmd' },
			output: 'command not found',
			durationMs: 10,
			status: 'error'
		};
		expect(tc.status).toBe('error');
	});
});

describe('ConfirmRequest interface', () => {
	it('accepts all required fields', () => {
		const cr: ConfirmRequest = {
			callId: 'cr-001',
			tool: 'email_send',
			params: { to: 'user@example.com', subject: 'Test' },
			timeoutS: 60,
			createdAt: new Date()
		};
		expect(cr.callId).toBe('cr-001');
		expect(cr.tool).toBe('email_send');
		expect(cr.timeoutS).toBe(60);
		expect(cr.createdAt).toBeInstanceOf(Date);
	});
});

describe('Session interface', () => {
	it('accepts required fields', () => {
		const session: Session = {
			id: 'sess-001',
			user: 'thomas',
			startedAt: '2026-03-01T10:00:00Z',
			messageCount: 5,
			toolCount: 2,
			agentsUsed: ['homelab', 'general']
		};
		expect(session.id).toBe('sess-001');
		expect(session.name).toBeUndefined();
		expect(session.endedAt).toBeUndefined();
	});

	it('accepts optional name and endedAt', () => {
		const session: Session = {
			id: 'sess-002',
			user: 'thomas',
			name: 'Docker troubleshooting',
			startedAt: '2026-03-01T09:00:00Z',
			endedAt: '2026-03-01T09:30:00Z',
			messageCount: 12,
			toolCount: 8,
			agentsUsed: ['homelab']
		};
		expect(session.name).toBe('Docker troubleshooting');
		expect(session.endedAt).toBe('2026-03-01T09:30:00Z');
	});
});

describe('AgentStatus type', () => {
	it('accepts all valid status values', () => {
		const statuses: AgentStatus[] = ['idle', 'thinking', 'streaming', 'done', 'error'];
		expect(statuses).toHaveLength(5);
		expect(statuses).toContain('idle');
		expect(statuses).toContain('thinking');
		expect(statuses).toContain('streaming');
		expect(statuses).toContain('done');
		expect(statuses).toContain('error');
	});
});

describe('ConnectionStatus type', () => {
	it('accepts all valid connection status values', () => {
		const statuses: ConnectionStatus[] = ['connected', 'connecting', 'disconnected', 'error'];
		expect(statuses).toHaveLength(4);
		expect(statuses).toContain('connected');
		expect(statuses).toContain('connecting');
		expect(statuses).toContain('disconnected');
		expect(statuses).toContain('error');
	});
});

describe('ClientMessage type', () => {
	it('chat message requires message field', () => {
		const msg: ClientMessage = { type: 'chat', message: 'hello' };
		expect(msg.type).toBe('chat');
	});

	it('chat message accepts optional model', () => {
		const msg: ClientMessage = { type: 'chat', message: 'hello', model: 'claude-sonnet-4-6' };
		expect(msg.type).toBe('chat');
	});

	it('chat message accepts requires_tools hint', () => {
		const msg: ClientMessage = {
			type: 'chat',
			message: '/skill summarize logs',
			requires_tools: true
		};
		expect(msg.type).toBe('chat');
		if (msg.type === 'chat') {
			expect(msg.requires_tools).toBe(true);
		}
	});

	it('ping message has no extra fields', () => {
		const msg: ClientMessage = { type: 'ping' };
		expect(msg.type).toBe('ping');
	});
});

describe('ServerMessage init type', () => {
	it('init message carries models and agents', () => {
		const msg: ServerMessage = {
			type: 'init',
			models: [{ id: 'claude-sonnet-4-6', label: 'Sonnet', backend: 'claude', available: true }],
			default_model: 'claude-sonnet-4-6',
			agents: [{ id: 'general', label: 'General' }],
			default_agent: 'general'
		};
		expect(msg.type).toBe('init');
		if (msg.type === 'init') {
			expect(msg.models).toHaveLength(1);
			expect(msg.agents).toHaveLength(1);
			expect(msg.default_model).toBe('claude-sonnet-4-6');
			expect(msg.default_agent).toBe('general');
			expect(msg.session_name).toBeUndefined();
		}
	});

	it('init message accepts optional session_name', () => {
		const msg: ServerMessage = {
			type: 'init',
			models: [],
			default_model: '',
			agents: [],
			default_agent: '',
			session_name: 'Docker troubleshooting'
		};
		if (msg.type === 'init') {
			expect(msg.session_name).toBe('Docker troubleshooting');
		}
	});
});

describe('ServerMessage subagent types', () => {
	it('subagent_start message is valid', () => {
		const msg: ServerMessage = {
			type: 'subagent_start',
			agent: 'homelab',
			parent: 'general'
		};
		expect(msg.type).toBe('subagent_start');
	});

	it('subagent_stop message includes cost', () => {
		const msg: ServerMessage = {
			type: 'subagent_stop',
			agent: 'homelab',
			cost_usd: 0.02
		};
		expect(msg.type).toBe('subagent_stop');
		if (msg.type === 'subagent_stop') {
			expect(msg.cost_usd).toBe(0.02);
		}
	});
});

describe('ServerMessage agent_status type', () => {
	it('agent_status message carries agent and status', () => {
		const msg: ServerMessage = {
			type: 'agent_status',
			agent: 'homelab',
			status: 'thinking'
		};
		expect(msg.type).toBe('agent_status');
		if (msg.type === 'agent_status') {
			expect(msg.agent).toBe('homelab');
			expect(msg.status).toBe('thinking');
		}
	});
});

describe('ServerMessage error type', () => {
	it('supports capability mismatch metadata', () => {
		const msg: ServerMessage = {
			type: 'error',
			error: 'model_capability_mismatch',
			message: 'Selected model cannot run tools',
			model: 'ollama/llama3.2:3b',
			capability: 'tools',
			suggested_model: 'sonnet'
		};
		expect(msg.type).toBe('error');
		if (msg.type === 'error') {
			expect(msg.capability).toBe('tools');
			expect(msg.suggested_model).toBe('sonnet');
		}
	});
});
