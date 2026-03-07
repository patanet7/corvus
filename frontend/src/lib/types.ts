export interface ModelCapabilities {
	supports_tools: boolean;
	supports_streaming: boolean;
}

// Model info pushed from the backend (ModelRouter is single source of truth)
export interface ModelInfo {
	id: string;
	label: string;
	backend: string;
	available: boolean;
	description?: string;
	isDefault?: boolean;
	capabilities?: ModelCapabilities;
}

// Agent info pushed from the backend
export interface AgentInfo {
	id: string;
	label: string;
	description?: string;
	isDefault?: boolean;
	runtimeStatus?: 'active' | 'busy' | 'offline' | 'degraded';
	currentModel?: string | null;
	queueDepth?: number;
	complexity?: string;
	toolModules?: string[];
	memoryDomain?: string;
	hasPrompt?: boolean;
	lastRunAt?: string;
}

export type DispatchMode = 'router' | 'direct' | 'parallel';

// Client -> Server message types
export type ClientMessage =
	| {
			type: 'chat';
			message: string;
			model?: string;
			target_agent?: string;
			target_agents?: string[];
			dispatch_mode?: DispatchMode;
			requires_tools?: boolean;
	  }
	| { type: 'confirm_response'; tool_call_id: string; approved: boolean }
	| { type: 'interrupt' }
	| { type: 'ping' };

// Server -> Client message types
export type ServerMessage =
	| { type: 'routing'; agent: string; model: string }
	| { type: 'agent_status'; agent: string; status: AgentStatus }
	| { type: 'text'; content: string; agent?: string; model?: string }
	| { type: 'tool_start'; tool: string; params: Record<string, unknown>; call_id: string }
	| {
			type: 'tool_result';
			call_id: string;
			output: string;
			duration_ms: number;
			status: 'success' | 'error';
		}
	| {
			type: 'tool_permission_decision';
			agent: string;
			tool: string;
			allowed: boolean;
			state: 'allow' | 'deny' | 'confirm';
			scope?: string;
			reason?: string;
	  }
	| {
			type: 'confirm_request';
			tool: string;
			params: Record<string, unknown>;
			call_id: string;
			timeout_s: number;
		}
	| { type: 'subagent_start'; agent: string; parent: string }
	| { type: 'subagent_stop'; agent: string; cost_usd: number }
	| { type: 'memory_changed'; domain: string; action: string; summary: string }
	| {
			type: 'dispatch_start';
			dispatch_id: string;
			session_id: string;
			turn_id: string;
			dispatch_mode: DispatchMode;
			target_agents: string[];
			message: string;
	  }
	| {
			type: 'run_start';
			dispatch_id: string;
			run_id: string;
			task_id?: string;
			session_id: string;
			turn_id: string;
			agent: string;
			backend?: string;
			model?: string;
			status?: string;
	  }
	| {
			type: 'run_phase';
			dispatch_id: string;
			run_id: string;
			task_id?: string;
			session_id: string;
			turn_id: string;
			agent: string;
			phase: 'queued' | 'routing' | 'planning' | 'executing' | 'compacting' | 'done' | 'error';
			summary: string;
	  }
	| {
			type: 'run_output_chunk';
			dispatch_id: string;
			run_id: string;
			task_id?: string;
			session_id: string;
			turn_id: string;
			agent: string;
			model?: string;
			chunk_index: number;
			content: string;
			final: boolean;
			tokens_used?: number;
			cost_usd?: number;
			context_limit?: number;
			context_pct?: number;
	  }
	| {
			type: 'run_complete';
			dispatch_id: string;
			run_id: string;
			task_id?: string;
			session_id: string;
			turn_id: string;
			agent: string;
			result: 'success' | 'error';
			summary: string;
			cost_usd: number;
			tokens_used?: number;
			context_limit?: number;
			context_pct?: number;
	  }
	| {
			type: 'dispatch_complete';
			dispatch_id: string;
			session_id: string;
			turn_id: string;
			status: 'done' | 'error';
			total_runs: number;
			success_count: number;
			error_count: number;
			cost_usd: number;
	  }
	| {
			type: 'done';
			session_id: string;
			cost_usd: number;
			tokens_used: number;
			context_limit: number;
			context_pct: number;
		}
	| {
			type: 'task_start';
			task_id: string;
			agent: string;
			description: string;
			session_id?: string;
			turn_id?: string;
	  }
	| {
			type: 'task_progress';
			task_id: string;
			agent: string;
			status: AgentStatus;
			summary: string;
			session_id?: string;
			turn_id?: string;
	  }
	| {
			type: 'task_complete';
			task_id: string;
			agent: string;
			result: 'success' | 'error';
			summary: string;
			cost_usd: number;
			session_id?: string;
			turn_id?: string;
		}
	| {
			type: 'init';
			models: ModelInfo[];
			default_model: string;
			agents: AgentInfo[];
			default_agent: string;
			session_id?: string;
			session_name?: string;
	  }
	| {
			type: 'error';
			message: string;
			error?: string;
			model?: string;
			capability?: string;
			suggested_model?: string;
	  }
	| { type: 'pong' };

export type AgentStatus = 'idle' | 'thinking' | 'streaming' | 'done' | 'error';

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error';

export type AgentName = string;

/** Validate agent name against optional live agent list, or by format. */
export function isValidAgentName(name: string, knownAgents?: AgentInfo[]): boolean {
	if (!name) return false;
	if (knownAgents) return knownAgents.some((a) => a.id === name);
	return /^[a-z][a-z0-9_-]*$/.test(name);
}

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	agent?: AgentName;
	model?: string;
	timestamp: Date;
	runtimeEvents?: ChatRuntimeEvent[];
	toolCalls?: ToolCall[];
	confirmRequest?: ConfirmRequest;
	isError?: boolean;
}

export type ChatRuntimeEventKind =
	| 'thinking'
	| 'reasoning'
	| 'phase'
	| 'tool_start'
	| 'tool_result'
	| 'confirm_request'
	| 'todo'
	| 'result'
	| 'info';

export interface ChatRuntimeEvent {
	id: string;
	kind: ChatRuntimeEventKind;
	summary: string;
	timestamp: Date;
	detail?: string;
	callId?: string;
}

export type AttachmentKind = 'file' | 'image' | 'audio';

export interface DraftAttachment {
	id: string;
	kind: AttachmentKind;
	name: string;
	sizeBytes: number;
	mimeType?: string;
}

export interface ToolCall {
	callId: string;
	tool: string;
	params: Record<string, unknown>;
	output?: string;
	durationMs?: number;
	status: 'running' | 'success' | 'error';
}

export interface ConfirmRequest {
	callId: string;
	tool: string;
	params: Record<string, unknown>;
	timeoutS: number;
	createdAt: Date;
}

export interface Session {
	id: string;
	user: string;
	name?: string;
	startedAt: string;
	endedAt?: string;
	messageCount: number;
	toolCount: number;
	agentsUsed: string[];
}

export interface Task {
	id: string;
	agent: AgentName;
	dispatchId?: string;
	runId?: string;
	description: string;
	status: AgentStatus;
	phase?: 'queued' | 'routing' | 'planning' | 'executing' | 'compacting' | 'done' | 'error';
	summary: string;
	result?: 'success' | 'error';
	costUsd: number;
	startedAt: Date;
	completedAt?: Date;
	messages: ChatMessage[];
	turnId?: string;
	sessionId?: string;
	events?: TaskEvent[];
}

export interface TaskEvent {
	kind:
		| 'task_progress'
		| 'run_phase'
		| 'run_output_chunk'
		| 'tool_start'
		| 'tool_result'
		| 'tool_permission_decision'
		| 'confirm_request'
		| 'info';
	timestamp: Date;
	text: string;
	callId?: string;
}

export interface SessionEvent {
	id: number;
	sessionId: string;
	turnId?: string;
	eventType: string;
	payload: Record<string, unknown>;
	createdAt: Date;
}

export interface TraceEvent {
	id: number;
	sourceApp: string;
	sessionId: string;
	dispatchId?: string;
	runId?: string;
	turnId?: string;
	hookEventType: string;
	payload: Record<string, unknown>;
	summary?: string;
	modelName?: string;
	timestamp: Date;
}

export interface TraceFilterOptions {
	sourceApps: string[];
	sessionIds: string[];
	hookEventTypes: string[];
}
