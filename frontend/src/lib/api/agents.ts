import type { AgentInfo, Session } from '$lib/types';
import { ApiError } from '$lib/api/sessions';

interface ApiAgent {
	id?: string;
	name?: string;
	label?: string;
	description?: string;
	isDefault?: boolean;
	runtime_status?: 'active' | 'busy' | 'offline' | 'degraded';
	current_model?: string | null;
	queue_depth?: number;
	complexity?: string;
	tool_modules?: string[];
	memory_domain?: string;
	has_prompt?: boolean;
	last_run_at?: string | null;
}

interface ApiAgentModelConfig {
	preferred?: string | null;
	fallback?: string | null;
	auto?: boolean;
	complexity?: string;
}

interface ApiAgentToolConfig {
	builtin?: string[];
	modules?: Record<string, Record<string, unknown>>;
	confirm_gated?: string[];
}

interface ApiAgentMemoryConfig {
	own_domain?: string;
	readable_domains?: string[] | null;
	can_read_shared?: boolean;
	can_write?: boolean;
}

interface ApiAgentDetail {
	id?: string;
	name: string;
	description: string;
	enabled?: boolean;
	prompt_file?: string | null;
	resolved_model?: string | null;
	models?: ApiAgentModelConfig;
	tools?: ApiAgentToolConfig;
	memory?: ApiAgentMemoryConfig | null;
	metadata?: Record<string, unknown>;
	recent_runs?: AgentRun[];
}

interface ApiPromptPreviewLayer {
	id: string;
	title: string;
	source: string;
	char_count: number;
	clipped: boolean;
	content_preview: string;
}

interface ApiPromptPreview {
	agent: string;
	safe_mode: boolean;
	total_layers: number;
	total_chars: number;
	full_preview: string;
	full_preview_clipped: boolean;
	layers: ApiPromptPreviewLayer[];
}

interface ApiPolicyEntry {
	key: string;
	scope: string;
	subject: string;
	state: 'allow' | 'confirm' | 'deny' | string;
	reason: string;
}

interface ApiPolicyMatrix {
	agent: string;
	entries: ApiPolicyEntry[];
	runtime?: {
		permission_mode?: string;
	};
	summary: {
		total: number;
		allow: number;
		confirm: number;
		deny: number;
	};
}

interface ApiAgentTodoItem {
	id: string;
	content: string;
	status: string;
	active_form?: string | null;
}

interface ApiAgentTodoFile {
	id: string;
	session_id?: string | null;
	updated_at: string;
	item_count: number;
	summary?: {
		pending?: number;
		in_progress?: number;
		completed?: number;
		other?: number;
	};
	items?: ApiAgentTodoItem[];
}

interface ApiAgentTodos {
	agent: string;
	scope?: string;
	files?: ApiAgentTodoFile[];
	totals?: {
		files?: number;
		items?: number;
		pending?: number;
		in_progress?: number;
		completed?: number;
		other?: number;
	};
}

export interface AgentProfile {
	id: string;
	label: string;
	description: string;
	enabled: boolean;
	promptFile?: string;
	resolvedModel?: string;
	preferredModel?: string;
	fallbackModel?: string;
	autoModelRouting: boolean;
	complexity?: string;
	memoryDomain?: string;
	readableDomains: string[];
	canReadShared: boolean;
	canWriteMemory: boolean;
	builtinTools: string[];
	confirmGatedTools: string[];
	moduleConfig: Record<string, Record<string, unknown>>;
	metadata: Record<string, unknown>;
	recentRuns: AgentRun[];
}

export interface CapabilityHealth {
	name: string;
	status: string;
	message: string;
}

export interface AgentPromptPreviewLayer {
	id: string;
	title: string;
	source: string;
	charCount: number;
	clipped: boolean;
	contentPreview: string;
}

export interface AgentPromptPreview {
	agent: string;
	safeMode: boolean;
	totalLayers: number;
	totalChars: number;
	fullPreview: string;
	fullPreviewClipped: boolean;
	layers: AgentPromptPreviewLayer[];
}

export interface AgentPolicyEntry {
	key: string;
	scope: string;
	subject: string;
	state: 'allow' | 'confirm' | 'deny' | string;
	reason: string;
}

export interface AgentPolicyMatrix {
	agent: string;
	entries: AgentPolicyEntry[];
	runtime: {
		permissionMode: string;
	};
	summary: {
		total: number;
		allow: number;
		confirm: number;
		deny: number;
	};
}

export interface AgentTodoItem {
	id: string;
	content: string;
	status: string;
	activeForm?: string;
}

export interface AgentTodoFile {
	id: string;
	sessionId?: string;
	updatedAt: string;
	itemCount: number;
	summary: {
		pending: number;
		inProgress: number;
		completed: number;
		other: number;
	};
	items: AgentTodoItem[];
}

export interface AgentTodoSnapshot {
	agent: string;
	scope: string;
	files: AgentTodoFile[];
	totals: {
		files: number;
		items: number;
		pending: number;
		inProgress: number;
		completed: number;
		other: number;
	};
}

export interface CreateAgentDraft {
	name: string;
	description: string;
	memoryDomain?: string;
	preferredModel?: string;
	builtinTools?: string[];
	moduleNames?: string[];
	confirmGatedTools?: string[];
	permissionMode?: 'default' | 'acceptEdits' | 'plan' | 'bypassPermissions';
}

interface ApiSession {
	id: string;
	user: string;
	started_at: string;
	ended_at?: string | null;
	summary?: string | null;
	message_count: number;
	tool_count: number;
	agents_used: string[];
}

export interface AgentRun {
	id: string;
	dispatch_id: string;
	session_id: string;
	turn_id?: string;
	agent: string;
	backend?: string;
	model?: string;
	status: string;
	summary?: string;
	cost_usd: number;
	tokens_used: number;
	context_limit: number;
	context_pct: number;
	error?: string;
	started_at: string;
	completed_at?: string;
}

export interface RunEvent {
	id: number;
	run_id: string;
	dispatch_id: string;
	session_id: string;
	turn_id?: string;
	event_type: string;
	payload: Record<string, unknown>;
	created_at: string;
}

function toAgentInfo(raw: ApiAgent): AgentInfo {
	const id = raw.id ?? raw.name ?? 'general';
	return {
		id,
		label: raw.label ?? id[0].toUpperCase() + id.slice(1),
		description: raw.description,
		isDefault: raw.isDefault,
		runtimeStatus: raw.runtime_status,
		currentModel: raw.current_model ?? undefined,
		queueDepth: raw.queue_depth,
		complexity: raw.complexity,
		toolModules: raw.tool_modules ?? [],
		memoryDomain: raw.memory_domain,
		hasPrompt: raw.has_prompt,
		lastRunAt: raw.last_run_at ?? undefined
	};
}

function toAgentProfile(raw: ApiAgentDetail): AgentProfile {
	const id = raw.id ?? raw.name;
	const models = raw.models ?? {};
	const tools = raw.tools ?? {};
	const memory = raw.memory ?? {};
	return {
		id,
		label: id[0].toUpperCase() + id.slice(1),
		description: raw.description,
		enabled: raw.enabled !== false,
		promptFile: raw.prompt_file ?? undefined,
		resolvedModel: raw.resolved_model ?? undefined,
		preferredModel: models.preferred ?? undefined,
		fallbackModel: models.fallback ?? undefined,
		autoModelRouting: models.auto !== false,
		complexity: models.complexity ?? undefined,
		memoryDomain: memory.own_domain ?? undefined,
		readableDomains: memory.readable_domains ?? [],
		canReadShared: memory.can_read_shared !== false,
		canWriteMemory: memory.can_write !== false,
		builtinTools: tools.builtin ?? [],
		confirmGatedTools: tools.confirm_gated ?? [],
		moduleConfig: tools.modules ?? {},
		metadata: raw.metadata ?? {},
		recentRuns: raw.recent_runs ?? []
	};
}

function toSession(api: ApiSession): Session {
	return {
		id: api.id,
		user: api.user,
		name: api.summary ?? undefined,
		startedAt: api.started_at,
		endedAt: api.ended_at ?? undefined,
		messageCount: api.message_count,
		toolCount: api.tool_count,
		agentsUsed: api.agents_used ?? []
	};
}

export async function listAgents(): Promise<AgentInfo[]> {
	const response = await fetch('/api/agents');
	if (!response.ok) {
		throw new ApiError(`Failed to load agents (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiAgent[];
	return body.map(toAgentInfo);
}

export async function listAgentSessions(agentName: string, limit = 50): Promise<Session[]> {
	const response = await fetch(`/api/agents/${agentName}/sessions?limit=${limit}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load agent sessions (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiSession[];
	return body.map(toSession);
}

export async function listAgentRuns(agentName: string, status?: string): Promise<AgentRun[]> {
	const qs = new URLSearchParams();
	if (status) qs.set('status', status);
	const response = await fetch(`/api/agents/${agentName}/runs${qs.size ? `?${qs.toString()}` : ''}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load agent runs (${response.status})`, response.status);
	}
	return (await response.json()) as AgentRun[];
}

export async function listRunEvents(runId: string, limit = 2000): Promise<RunEvent[]> {
	const response = await fetch(`/api/runs/${runId}/events?limit=${limit}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load run events (${response.status})`, response.status);
	}
	return (await response.json()) as RunEvent[];
}

export async function getAgentProfile(agentName: string): Promise<AgentProfile> {
	const response = await fetch(`/api/agents/${agentName}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load agent profile (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiAgentDetail;
	return toAgentProfile(body);
}

export async function getCapabilityHealth(moduleName: string): Promise<CapabilityHealth> {
	const response = await fetch(`/api/capabilities/${moduleName}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load capability health (${response.status})`, response.status);
	}
	const body = (await response.json()) as { name: string; status: string; message: string };
	return {
		name: body.name,
		status: body.status,
		message: body.message
	};
}

export async function getAgentPromptPreview(
	agentName: string,
	options?: { includeWorkspace?: boolean; maxChars?: number; clipChars?: number }
): Promise<AgentPromptPreview> {
	const qs = new URLSearchParams();
	if (options?.includeWorkspace !== undefined) {
		qs.set('include_workspace', options.includeWorkspace ? 'true' : 'false');
	}
	if (options?.maxChars !== undefined) {
		qs.set('max_chars', String(options.maxChars));
	}
	if (options?.clipChars !== undefined) {
		qs.set('clip_chars', String(options.clipChars));
	}
	const response = await fetch(
		`/api/agents/${agentName}/prompt-preview${qs.size ? `?${qs.toString()}` : ''}`
	);
	if (!response.ok) {
		throw new ApiError(`Failed to load prompt preview (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiPromptPreview;
	return {
		agent: body.agent,
		safeMode: body.safe_mode,
		totalLayers: body.total_layers,
		totalChars: body.total_chars,
		fullPreview: body.full_preview,
		fullPreviewClipped: body.full_preview_clipped,
		layers: (body.layers ?? []).map((layer) => ({
			id: layer.id,
			title: layer.title,
			source: layer.source,
			charCount: layer.char_count,
			clipped: layer.clipped,
			contentPreview: layer.content_preview
		}))
	};
}

export async function getAgentPolicy(agentName: string): Promise<AgentPolicyMatrix> {
	const response = await fetch(`/api/agents/${agentName}/policy`);
	if (!response.ok) {
		throw new ApiError(`Failed to load agent policy (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiPolicyMatrix;
	return {
		agent: body.agent,
		entries: body.entries ?? [],
		runtime: {
			permissionMode: body.runtime?.permission_mode ?? 'default'
		},
		summary: {
			total: body.summary?.total ?? 0,
			allow: body.summary?.allow ?? 0,
			confirm: body.summary?.confirm ?? 0,
			deny: body.summary?.deny ?? 0
		}
	};
}

export async function getAgentTodos(
	agentName: string,
	options?: { limitFiles?: number; limitItems?: number }
): Promise<AgentTodoSnapshot> {
	const qs = new URLSearchParams();
	if (options?.limitFiles !== undefined) {
		qs.set('limit_files', String(options.limitFiles));
	}
	if (options?.limitItems !== undefined) {
		qs.set('limit_items', String(options.limitItems));
	}
	const response = await fetch(`/api/agents/${agentName}/todos${qs.size ? `?${qs.toString()}` : ''}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load agent todos (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiAgentTodos;
	return {
		agent: body.agent,
		scope: body.scope ?? 'unknown',
		files: (body.files ?? []).map((file) => ({
			id: file.id,
			sessionId: file.session_id ?? undefined,
			updatedAt: file.updated_at,
			itemCount: file.item_count,
			summary: {
				pending: file.summary?.pending ?? 0,
				inProgress: file.summary?.in_progress ?? 0,
				completed: file.summary?.completed ?? 0,
				other: file.summary?.other ?? 0
			},
			items: (file.items ?? []).map((item) => ({
				id: item.id,
				content: item.content,
				status: item.status,
				activeForm: item.active_form ?? undefined
			}))
		})),
		totals: {
			files: body.totals?.files ?? 0,
			items: body.totals?.items ?? 0,
			pending: body.totals?.pending ?? 0,
			inProgress: body.totals?.in_progress ?? 0,
			completed: body.totals?.completed ?? 0,
			other: body.totals?.other ?? 0
		}
	};
}

export async function listDispatchEvents(
	dispatchId: string,
	limit = 4000
): Promise<RunEvent[]> {
	const response = await fetch(`/api/dispatch/${dispatchId}/events?limit=${limit}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load dispatch events (${response.status})`, response.status);
	}
	return (await response.json()) as RunEvent[];
}

function normalizeStringList(values: string[] | undefined): string[] {
	if (!values || values.length === 0) return [];
	return Array.from(
		new Set(
			values
				.map((value) => value.trim())
				.filter((value) => value.length > 0)
		)
	);
}

export async function createAgent(draft: CreateAgentDraft): Promise<{ status: string; name: string }> {
	const name = draft.name.trim();
	const description = draft.description.trim();
	if (!name) {
		throw new Error('Agent name is required');
	}
	if (!description) {
		throw new Error('Agent description is required');
	}

	const builtinTools = normalizeStringList(draft.builtinTools);
	const moduleNames = normalizeStringList(draft.moduleNames);
	const confirmGatedTools = normalizeStringList(draft.confirmGatedTools);
	const moduleConfig = Object.fromEntries(moduleNames.map((moduleName) => [moduleName, {}]));
	const permissionMode = draft.permissionMode?.trim() ?? 'default';

	const payload: Record<string, unknown> = {
		name,
		description
	};

	if (draft.memoryDomain?.trim()) {
		payload.memory = { own_domain: draft.memoryDomain.trim() };
	}
	if (draft.preferredModel?.trim()) {
		payload.models = { preferred: draft.preferredModel.trim() };
	}
	if (builtinTools.length > 0 || moduleNames.length > 0 || confirmGatedTools.length > 0) {
		payload.tools = {
			builtin: builtinTools,
			modules: moduleConfig,
			confirm_gated: confirmGatedTools
		};
	}
	if (permissionMode && permissionMode !== 'default') {
		payload.metadata = { permission_mode: permissionMode };
	}

	const response = await fetch('/api/agents', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(payload)
	});
	if (!response.ok) {
		throw new ApiError(`Failed to create agent (${response.status})`, response.status);
	}
	return (await response.json()) as { status: string; name: string };
}
