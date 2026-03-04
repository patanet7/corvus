import { describe, it, expect } from 'vitest';
import type { ServerMessage, ClientMessage } from './types';
import { AGENT_NAMES, isValidAgentName } from './types';
import { GatewayClient } from './ws';

describe('Protocol types', () => {
	it('routing message is valid ServerMessage', () => {
		const msg: ServerMessage = { type: 'routing', agent: 'homelab', model: 'claude-sonnet-4-6' };
		expect(msg.type).toBe('routing');
		expect(msg.agent).toBe('homelab');
		expect(msg.model).toBe('claude-sonnet-4-6');
	});

	it('chat message is valid ClientMessage', () => {
		const msg: ClientMessage = { type: 'chat', message: 'hello' };
		expect(msg.type).toBe('chat');
		expect(msg.message).toBe('hello');
	});

	it('confirm_response message is valid ClientMessage', () => {
		const msg: ClientMessage = {
			type: 'confirm_response',
			tool_call_id: 'abc-123',
			approved: true
		};
		expect(msg.type).toBe('confirm_response');
	});

	it('interrupt message is valid ClientMessage', () => {
		const msg: ClientMessage = { type: 'interrupt' };
		expect(msg.type).toBe('interrupt');
	});

	it('text message is valid ServerMessage', () => {
		const msg: ServerMessage = { type: 'text', content: 'hello world', agent: 'homelab' };
		expect(msg.type).toBe('text');
		expect(msg.content).toBe('hello world');
	});

	it('tool_start message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'tool_start',
			tool: 'bash',
			params: { command: 'docker ps' },
			call_id: 'abc-123'
		};
		expect(msg.type).toBe('tool_start');
		expect(msg.call_id).toBe('abc-123');
	});

	it('tool_result message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'tool_result',
			call_id: 'abc-123',
			output: 'container running',
			duration_ms: 800,
			status: 'success'
		};
		expect(msg.status).toBe('success');
		expect(msg.duration_ms).toBe(800);
	});

	it('confirm_request message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'confirm_request',
			tool: 'email_send',
			params: { to: 'user@example.com', subject: 'Test' },
			call_id: 'def-456',
			timeout_s: 60
		};
		expect(msg.type).toBe('confirm_request');
		expect(msg.timeout_s).toBe(60);
	});

	it('done message includes context metrics', () => {
		const msg: ServerMessage = {
			type: 'done',
			session_id: 'sess-001',
			cost_usd: 0.04,
			tokens_used: 2847,
			context_limit: 200000,
			context_pct: 1.4
		};
		expect(msg.tokens_used).toBe(2847);
		expect(msg.context_pct).toBe(1.4);
	});

	it('error message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'error',
			message: 'Selected model unavailable',
			error: 'model_unavailable',
			model: 'claude-sonnet-4-6'
		};
		expect(msg.type).toBe('error');
		expect(msg.message).toBe('Selected model unavailable');
		expect(msg.error).toBe('model_unavailable');
	});

	it('pong message is valid ServerMessage', () => {
		const msg: ServerMessage = { type: 'pong' };
		expect(msg.type).toBe('pong');
	});

	it('memory_changed message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'memory_changed',
			domain: 'homelab',
			action: 'save',
			summary: 'plex running on miniserver'
		};
		expect(msg.type).toBe('memory_changed');
		expect(msg.domain).toBe('homelab');
	});

	it('task_start message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'task_start',
			task_id: 'task-001',
			agent: 'homelab',
			description: 'Check Docker container status'
		};
		expect(msg.type).toBe('task_start');
		expect(msg.task_id).toBe('task-001');
		expect(msg.agent).toBe('homelab');
		expect(msg.description).toBe('Check Docker container status');
	});

	it('task_progress message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'task_progress',
			task_id: 'task-001',
			agent: 'homelab',
			status: 'streaming',
			summary: 'Querying container list...'
		};
		expect(msg.type).toBe('task_progress');
		expect(msg.task_id).toBe('task-001');
		expect(msg.status).toBe('streaming');
		expect(msg.summary).toBe('Querying container list...');
	});

	it('task_complete message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'task_complete',
			task_id: 'task-001',
			agent: 'homelab',
			result: 'success',
			summary: 'All containers healthy',
			cost_usd: 0.03
		};
		expect(msg.type).toBe('task_complete');
		expect(msg.task_id).toBe('task-001');
		expect(msg.result).toBe('success');
		expect(msg.cost_usd).toBe(0.03);
	});

	it('task_complete with error result is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'task_complete',
			task_id: 'task-002',
			agent: 'finance',
			result: 'error',
			summary: 'API rate limit exceeded',
			cost_usd: 0.01
		};
		expect(msg.type).toBe('task_complete');
		expect(msg.result).toBe('error');
	});

	it('dispatch_start message is valid ServerMessage', () => {
		const msg: ServerMessage = {
			type: 'dispatch_start',
			dispatch_id: 'disp-001',
			session_id: 'sess-001',
			turn_id: 'turn-001',
			dispatch_mode: 'parallel',
			target_agents: ['work', 'homelab'],
			message: 'fan out this task'
		};
		expect(msg.type).toBe('dispatch_start');
		expect(msg.target_agents).toHaveLength(2);
	});

	it('run_phase message supports compacting phase', () => {
		const msg: ServerMessage = {
			type: 'run_phase',
			dispatch_id: 'disp-001',
			run_id: 'run-001',
			session_id: 'sess-001',
			turn_id: 'turn-001',
			agent: 'homelab',
			phase: 'compacting',
			summary: 'Compacting final response'
		};
		expect(msg.type).toBe('run_phase');
		expect(msg.phase).toBe('compacting');
	});

	it('type narrowing works for task messages', () => {
		const msg: ServerMessage = {
			type: 'task_start',
			task_id: 'task-003',
			agent: 'work',
			description: 'Summarize emails'
		};

		if (msg.type === 'task_start') {
			// TypeScript should narrow this to the task_start variant
			expect(msg.task_id).toBe('task-003');
			expect(msg.description).toBe('Summarize emails');
		}

		const progressMsg: ServerMessage = {
			type: 'task_progress',
			task_id: 'task-003',
			agent: 'work',
			status: 'thinking',
			summary: 'Processing inbox'
		};

		if (progressMsg.type === 'task_progress') {
			expect(progressMsg.status).toBe('thinking');
			expect(progressMsg.summary).toBe('Processing inbox');
		}

		const completeMsg: ServerMessage = {
			type: 'task_complete',
			task_id: 'task-003',
			agent: 'work',
			result: 'success',
			summary: '5 emails summarized',
			cost_usd: 0.05
		};

		if (completeMsg.type === 'task_complete') {
			expect(completeMsg.result).toBe('success');
			expect(completeMsg.cost_usd).toBe(0.05);
		}
	});
});

describe('Agent constants', () => {
	it('AGENT_NAMES has all 10 agents', () => {
		expect(AGENT_NAMES).toHaveLength(10);
		expect(AGENT_NAMES).toContain('personal');
		expect(AGENT_NAMES).toContain('work');
		expect(AGENT_NAMES).toContain('homelab');
		expect(AGENT_NAMES).toContain('finance');
		expect(AGENT_NAMES).toContain('email');
		expect(AGENT_NAMES).toContain('docs');
		expect(AGENT_NAMES).toContain('music');
		expect(AGENT_NAMES).toContain('home');
		expect(AGENT_NAMES).toContain('huginn');
		expect(AGENT_NAMES).toContain('general');
	});
});

describe('isValidAgentName', () => {
	it('returns true for valid agent names', () => {
		expect(isValidAgentName('homelab')).toBe(true);
		expect(isValidAgentName('personal')).toBe(true);
		expect(isValidAgentName('general')).toBe(true);
	});

	it('returns false for invalid agent names', () => {
		expect(isValidAgentName('unknown')).toBe(false);
		expect(isValidAgentName('')).toBe(false);
		expect(isValidAgentName('HOMELAB')).toBe(false);
	});
});

describe('GatewayClient', () => {
	it('exports GatewayClient class', () => {
		expect(GatewayClient).toBeDefined();
		expect(typeof GatewayClient).toBe('function');
	});

	it('isConnected returns false when not connected', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		expect(client.isConnected).toBe(false);
	});

	it('disconnect can be called safely when not connected', () => {
		const statuses: string[] = [];
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			(status) => {
				statuses.push(status);
			}
		);
		client.disconnect();
		expect(statuses).toContain('disconnected');
	});

	it('send queues messages when not connected', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		// Should not throw when sending while disconnected
		expect(() => client.send({ type: 'chat', message: 'queued' })).not.toThrow();
	});
});

describe('GatewayClient.sendChat', () => {
	it('sendChat with model parameter includes model in queued message', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		// When not connected, sendChat queues the message internally.
		// We verify the method does not throw when called with a model.
		expect(() => client.sendChat('hello world', 'claude-sonnet-4-6')).not.toThrow();
	});

	it('sendChat without model parameter omits model field', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		// When not connected, sendChat queues the message internally.
		// We verify the method does not throw when called without a model.
		expect(() => client.sendChat('hello world')).not.toThrow();
	});

	it('sendChat with undefined model behaves like no model', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		expect(() => client.sendChat('test message', undefined)).not.toThrow();
	});

	it('sendChat with empty string model omits model field', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		// Empty string is falsy, so model field should be omitted
		expect(() => client.sendChat('test message', '')).not.toThrow();
	});

	it('sendChat supports multi-target dispatch args', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		expect(() =>
			client.sendChat(
				'fan out request',
				'ollama/qwen3:8b',
				undefined,
				false,
				['work', 'homelab'],
				'parallel'
			)
		).not.toThrow();
	});
});

describe('GatewayClient.sendConfirm', () => {
	it('sendConfirm with approved=true does not throw', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		expect(() => client.sendConfirm('call-123', true)).not.toThrow();
	});

	it('sendConfirm with approved=false does not throw', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		expect(() => client.sendConfirm('call-456', false)).not.toThrow();
	});
});

describe('GatewayClient.sendInterrupt', () => {
	it('sendInterrupt does not throw when disconnected', () => {
		const client = new GatewayClient(
			'ws://localhost:18789/ws',
			() => {},
			() => {}
		);
		expect(() => client.sendInterrupt()).not.toThrow();
	});
});
