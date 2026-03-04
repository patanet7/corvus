import type {
	ChatMessage,
	ConnectionStatus,
	AgentStatus,
	Session,
	AgentName,
	Task,
	ToolCall,
	ConfirmRequest,
	ModelInfo,
	AgentInfo
} from './types';

// Connection state
export const connectionStatus = $state<{ value: ConnectionStatus }>({ value: 'disconnected' });

// Available models (populated from backend `init` message)
export const modelStore = $state<{
	models: ModelInfo[];
	defaultModel: string;
}>({
	models: [],
	defaultModel: ''
});

// Available agents (populated from backend `init` message)
export const agentStore = $state<{
	agents: AgentInfo[];
	defaultAgent: string;
}>({
	agents: [],
	defaultAgent: ''
});

// Current session
export const currentSession = $state<{
	id: string | null;
	name: string;
	messages: ChatMessage[];
	activeAgent: AgentName | null;
	agentStatus: AgentStatus;
	selectedModel: string;
	costUsd: number;
	tokensUsed: number;
	contextPct: number;
}>({
	id: null,
	name: 'Huginn',
	messages: [],
	activeAgent: null,
	agentStatus: 'idle',
	selectedModel: '',
	costUsd: 0,
	tokensUsed: 0,
	contextPct: 0
});

// Session list
export const sessions = $state<{ list: Session[] }>({ list: [] });

// Pending tool calls (for streaming tool_start -> tool_result)
export const pendingToolCalls = $state<{ calls: Map<string, ToolCall> }>({
	calls: new Map()
});

// Active confirm requests
export const activeConfirm = $state<{ request: ConfirmRequest | null }>({ request: null });

// Task tracking for multi-agent dispatch
export const taskStore = $state<{
	tasks: Map<string, Task>;
	activeTaskId: string | null;
}>({
	tasks: new Map(),
	activeTaskId: null
});

export function addTask(task: Task): void {
	taskStore.tasks.set(task.id, task);
}

export function updateTask(taskId: string, updates: Partial<Task>): void {
	const task = taskStore.tasks.get(taskId);
	if (task) {
		Object.assign(task, updates);
	}
}

export function getActiveTasks(): Task[] {
	return Array.from(taskStore.tasks.values()).filter(
		(t) => t.status !== 'done' && t.result === undefined
	);
}

export function clearCompletedTasks(): void {
	for (const [taskId, task] of taskStore.tasks.entries()) {
		const completed = task.status === 'done' || task.result !== undefined;
		if (completed) {
			taskStore.tasks.delete(taskId);
			if (taskStore.activeTaskId === taskId) {
				taskStore.activeTaskId = null;
			}
		}
	}
}
