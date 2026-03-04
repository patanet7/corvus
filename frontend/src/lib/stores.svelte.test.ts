import { describe, it, expect, beforeEach } from 'vitest';
import type { Task } from './types';
import {
	taskStore,
	addTask,
	updateTask,
	getActiveTasks,
	modelStore,
	agentStore,
	currentSession
} from './stores.svelte';

function createTask(overrides: Partial<Task> = {}): Task {
	return {
		id: 'task-001',
		agent: 'homelab',
		description: 'Check Docker containers',
		status: 'thinking',
		summary: '',
		costUsd: 0,
		startedAt: new Date('2026-03-01T10:00:00Z'),
		messages: [],
		...overrides
	};
}

beforeEach(() => {
	taskStore.tasks.clear();
	taskStore.activeTaskId = null;
});

describe('Task interface', () => {
	it('accepts all required fields', () => {
		const task: Task = {
			id: 'task-100',
			agent: 'finance',
			description: 'Fetch transaction report',
			status: 'idle',
			summary: '',
			costUsd: 0,
			startedAt: new Date(),
			messages: []
		};
		expect(task.id).toBe('task-100');
		expect(task.agent).toBe('finance');
		expect(task.status).toBe('idle');
		expect(task.result).toBeUndefined();
		expect(task.completedAt).toBeUndefined();
	});

	it('accepts optional result and completedAt fields', () => {
		const task: Task = {
			id: 'task-101',
			agent: 'work',
			description: 'Summarize PRs',
			status: 'done',
			summary: '3 PRs reviewed',
			result: 'success',
			costUsd: 0.05,
			startedAt: new Date('2026-03-01T09:00:00Z'),
			completedAt: new Date('2026-03-01T09:02:00Z'),
			messages: []
		};
		expect(task.result).toBe('success');
		expect(task.completedAt).toBeInstanceOf(Date);
	});

	it('result can be error', () => {
		const task: Task = {
			id: 'task-102',
			agent: 'email',
			description: 'Send newsletter',
			status: 'error',
			summary: 'SMTP connection refused',
			result: 'error',
			costUsd: 0.01,
			startedAt: new Date(),
			messages: []
		};
		expect(task.result).toBe('error');
	});
});

describe('taskStore initial state', () => {
	it('tasks map is empty', () => {
		expect(taskStore.tasks.size).toBe(0);
	});

	it('activeTaskId is null', () => {
		expect(taskStore.activeTaskId).toBeNull();
	});
});

describe('addTask', () => {
	it('adds a task to the store', () => {
		const task = createTask();
		addTask(task);
		expect(taskStore.tasks.size).toBe(1);
		expect(taskStore.tasks.get('task-001')).toBeDefined();
	});

	it('stores the correct task data', () => {
		const task = createTask({
			id: 'task-abc',
			agent: 'finance',
			description: 'Generate budget report'
		});
		addTask(task);
		const stored = taskStore.tasks.get('task-abc');
		expect(stored).toBeDefined();
		expect(stored!.agent).toBe('finance');
		expect(stored!.description).toBe('Generate budget report');
	});

	it('can add multiple tasks', () => {
		addTask(createTask({ id: 'task-a' }));
		addTask(createTask({ id: 'task-b' }));
		addTask(createTask({ id: 'task-c' }));
		expect(taskStore.tasks.size).toBe(3);
	});

	it('overwrites a task with the same id', () => {
		addTask(createTask({ id: 'task-dup', description: 'First' }));
		addTask(createTask({ id: 'task-dup', description: 'Second' }));
		expect(taskStore.tasks.size).toBe(1);
		expect(taskStore.tasks.get('task-dup')!.description).toBe('Second');
	});
});

describe('updateTask', () => {
	it('updates an existing task status', () => {
		addTask(createTask({ id: 'task-upd', status: 'thinking' }));
		updateTask('task-upd', { status: 'streaming' });
		expect(taskStore.tasks.get('task-upd')!.status).toBe('streaming');
	});

	it('updates summary and result together', () => {
		addTask(createTask({ id: 'task-upd2' }));
		updateTask('task-upd2', {
			status: 'done',
			summary: 'Completed successfully',
			result: 'success',
			costUsd: 0.04,
			completedAt: new Date('2026-03-01T10:05:00Z')
		});
		const updated = taskStore.tasks.get('task-upd2')!;
		expect(updated.status).toBe('done');
		expect(updated.summary).toBe('Completed successfully');
		expect(updated.result).toBe('success');
		expect(updated.costUsd).toBe(0.04);
		expect(updated.completedAt).toEqual(new Date('2026-03-01T10:05:00Z'));
	});

	it('does nothing when task id is not found', () => {
		addTask(createTask({ id: 'task-exists' }));
		updateTask('task-nonexistent', { status: 'error' });
		// The existing task should be unchanged
		expect(taskStore.tasks.get('task-exists')!.status).toBe('thinking');
		expect(taskStore.tasks.size).toBe(1);
	});

	it('preserves fields not included in updates', () => {
		addTask(
			createTask({
				id: 'task-partial',
				agent: 'homelab',
				description: 'Check containers',
				status: 'thinking'
			})
		);
		updateTask('task-partial', { summary: 'Running docker ps...' });
		const task = taskStore.tasks.get('task-partial')!;
		expect(task.agent).toBe('homelab');
		expect(task.description).toBe('Check containers');
		expect(task.status).toBe('thinking');
		expect(task.summary).toBe('Running docker ps...');
	});
});

describe('getActiveTasks', () => {
	it('returns empty array when no tasks exist', () => {
		expect(getActiveTasks()).toEqual([]);
	});

	it('returns tasks that are not done and have no result', () => {
		addTask(createTask({ id: 'task-active-1', status: 'thinking' }));
		addTask(createTask({ id: 'task-active-2', status: 'streaming' }));
		const active = getActiveTasks();
		expect(active).toHaveLength(2);
	});

	it('excludes tasks with status done', () => {
		addTask(createTask({ id: 'task-done', status: 'done' }));
		addTask(createTask({ id: 'task-active', status: 'thinking' }));
		const active = getActiveTasks();
		expect(active).toHaveLength(1);
		expect(active[0].id).toBe('task-active');
	});

	it('excludes tasks with a result set (even if status is not done)', () => {
		addTask(createTask({ id: 'task-with-result', status: 'error', result: 'error' }));
		addTask(createTask({ id: 'task-no-result', status: 'streaming' }));
		const active = getActiveTasks();
		expect(active).toHaveLength(1);
		expect(active[0].id).toBe('task-no-result');
	});

	it('excludes tasks with success result', () => {
		addTask(
			createTask({
				id: 'task-success',
				status: 'done',
				result: 'success',
				completedAt: new Date()
			})
		);
		addTask(createTask({ id: 'task-in-progress', status: 'thinking' }));
		const active = getActiveTasks();
		expect(active).toHaveLength(1);
		expect(active[0].id).toBe('task-in-progress');
	});

	it('returns empty when all tasks are completed', () => {
		addTask(createTask({ id: 't1', status: 'done', result: 'success' }));
		addTask(createTask({ id: 't2', status: 'done', result: 'error' }));
		expect(getActiveTasks()).toHaveLength(0);
	});

	it('includes idle tasks (not yet started processing)', () => {
		addTask(createTask({ id: 'task-idle', status: 'idle' }));
		const active = getActiveTasks();
		expect(active).toHaveLength(1);
		expect(active[0].status).toBe('idle');
	});
});

describe('modelStore initial state', () => {
	it('models array is empty', () => {
		expect(modelStore.models).toEqual([]);
	});

	it('defaultModel is empty string', () => {
		expect(modelStore.defaultModel).toBe('');
	});

	it('models is an array type', () => {
		expect(Array.isArray(modelStore.models)).toBe(true);
	});
});

describe('agentStore initial state', () => {
	it('agents array is empty', () => {
		expect(agentStore.agents).toEqual([]);
	});

	it('defaultAgent is empty string', () => {
		expect(agentStore.defaultAgent).toBe('');
	});

	it('agents is an array type', () => {
		expect(Array.isArray(agentStore.agents)).toBe(true);
	});
});

describe('currentSession initial state', () => {
	it('id is null', () => {
		expect(currentSession.id).toBeNull();
	});

	it('name is Huginn', () => {
		expect(currentSession.name).toBe('Huginn');
	});

	it('messages is empty array', () => {
		expect(currentSession.messages).toEqual([]);
	});

	it('activeAgent is null', () => {
		expect(currentSession.activeAgent).toBeNull();
	});

	it('agentStatus is idle', () => {
		expect(currentSession.agentStatus).toBe('idle');
	});

	it('selectedModel is empty string', () => {
		expect(currentSession.selectedModel).toBe('');
	});

	it('costUsd is 0', () => {
		expect(currentSession.costUsd).toBe(0);
	});

	it('tokensUsed is 0', () => {
		expect(currentSession.tokensUsed).toBe(0);
	});

	it('contextPct is 0', () => {
		expect(currentSession.contextPct).toBe(0);
	});
});
