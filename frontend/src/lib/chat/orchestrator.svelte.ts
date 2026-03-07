import { v4 as uuid } from 'uuid';

import { parseAgentMention, parseSlashCommand } from '$lib/chat/composer';
import {
	createSessionHistoryState,
	reduceSessionHistory
} from '$lib/chat/session-history';
import {
	loadModelPreferences,
	preferredModelForAgent,
	saveModelPreferences
} from '$lib/chat/model-preferences';
import { resolveFallbackModelId, resolvePreferredModelId } from '$lib/chat/model-selection';
import { pushToast } from '$lib/chat/toasts.svelte';
import {
	ApiError,
	deleteSession,
	listSessionEvents,
	listSessionMessages,
	listSessions,
	renameSession
} from '$lib/api/sessions';
import { RunOutputOrderer, type RunOutputChunk } from '$lib/chat/run-output-order';
import type {
	AgentStatus,
	ChatMessage,
	ChatRuntimeEvent,
	DispatchMode,
	SessionEvent,
	ServerMessage,
	Task,
	TaskEvent,
	ToolCall
} from '$lib/types';
import { isValidAgentName } from '$lib/types';
import { GatewayClient } from '$lib/ws';
import {
	activeConfirm,
	addTask,
	agentStore,
	connectionStatus,
	currentSession,
	modelStore,
	pendingToolCalls,
	sessions,
	taskStore,
	updateTask
} from '$lib/stores.svelte';

export type AppMode = 'chat' | 'agents' | 'tasks' | 'timeline' | 'memory' | 'config';
export type ModelSelectionMode = 'preferred' | 'manual';

export const chatUiState = $state<{
	lastRoutedAgent: string | null;
	lastRoutedModel: string | null;
	modelSelectionMode: ModelSelectionMode;
	pinnedAgent: string | null;
	dispatchMode: DispatchMode;
	selectedRecipients: string[];
	sendToAllRecipients: boolean;
	modelPreferences: Record<string, string>;
	history: ReturnType<typeof createSessionHistoryState>;
}>({
	lastRoutedAgent: null,
	lastRoutedModel: null,
	modelSelectionMode: 'preferred',
	pinnedAgent: null,
	dispatchMode: 'router',
	selectedRecipients: [],
	sendToAllRecipients: false,
	modelPreferences: {},
	history: createSessionHistoryState()
});

let client: GatewayClient | null = null;
let onModeRequest: ((mode: AppMode) => void) | null = null;
let modelPreferencesLoaded = false;
const BACKEND_DISABLED = import.meta.env.VITE_DISABLE_BACKEND === '1';
const runOutputOrderer = new RunOutputOrderer();
let runtimeEventSeq = 0;

export function setModeRequestHandler(handler: ((mode: AppMode) => void) | null): void {
	onModeRequest = handler;
}

function ensureModelPreferencesLoaded(): void {
	if (modelPreferencesLoaded) return;
	chatUiState.modelPreferences = loadModelPreferences();
	modelPreferencesLoaded = true;
}

function updateModelPreference(agent: string, modelId: string): void {
	ensureModelPreferencesLoaded();
	chatUiState.modelPreferences[agent] = modelId;
	saveModelPreferences(chatUiState.modelPreferences);
}

function applyPinnedAgentPreference(agent: string): void {
	ensureModelPreferencesLoaded();
	const preferred = preferredModelForAgent(agent, chatUiState.modelPreferences);
	if (!preferred) return;
	chatUiState.modelSelectionMode = 'manual';
	currentSession.selectedModel = preferred;
}

function isKnownEnabledAgent(name: string): boolean {
	if (!isValidAgentName(name)) return false;
	if (agentStore.agents.length === 0) return true;
	return agentStore.agents.some((agent) => agent.id === name);
}

function pushLocalAssistantNote(content: string): void {
	const note: ChatMessage = {
		id: uuid(),
		role: 'assistant',
		content,
		timestamp: new Date(),
		agent: 'general'
	};
	currentSession.messages.push(note);
}

function resetLocalSessionState(): void {
	currentSession.messages = [];
	currentSession.id = null;
	currentSession.name = agentStore.defaultAgent || 'Huginn';
	currentSession.activeAgent = null;
	currentSession.agentStatus = 'idle';
	currentSession.selectedModel = resolvePreferredModelId(modelStore.defaultModel, modelStore.models);
	currentSession.costUsd = 0;
	currentSession.tokensUsed = 0;
	currentSession.contextPct = 0;
	chatUiState.lastRoutedAgent = null;
	chatUiState.lastRoutedModel = null;
	taskStore.tasks.clear();
	taskStore.activeTaskId = null;
	runOutputOrderer.resetAll();
	runtimeEventSeq = 0;
	chatUiState.modelSelectionMode = 'preferred';
	chatUiState.pinnedAgent = null;
	chatUiState.dispatchMode = 'router';
	chatUiState.selectedRecipients = [];
	chatUiState.sendToAllRecipients = false;
	chatUiState.history = reduceSessionHistory(chatUiState.history, { type: 'transcript_reset' });
}

function buildWsUrl(resumeSessionId?: string): string {
	const isDev = location.port === '5173';
	const wsHost = isDev ? `${location.hostname}:18789` : location.host;
	const base = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${wsHost}/ws`;
	if (!resumeSessionId) return base;
	const qs = new URLSearchParams({ session_id: resumeSessionId });
	return `${base}?${qs.toString()}`;
}

function connectSocket(resumeSessionId?: string): void {
	if (client) {
		client.disconnect();
		client = null;
	}
	client = new GatewayClient(
		buildWsUrl(resumeSessionId),
		handleMessage,
		(status) => {
			connectionStatus.value = status;
			if (status === 'disconnected' || status === 'error') {
				currentSession.agentStatus = 'idle';
			}
		}
	);
	client.connect();
}

export async function loadSessionsData(): Promise<void> {
	if (BACKEND_DISABLED) {
		sessions.list = [];
		chatUiState.history = reduceSessionHistory(chatUiState.history, { type: 'sessions_load_success' });
		return;
	}
	chatUiState.history = reduceSessionHistory(chatUiState.history, { type: 'sessions_load_start' });
	try {
		sessions.list = await listSessions(50);
		chatUiState.history = reduceSessionHistory(chatUiState.history, { type: 'sessions_load_success' });
	} catch (error) {
		if (error instanceof ApiError) {
			chatUiState.history = reduceSessionHistory(chatUiState.history, {
				type: 'sessions_load_error',
				error: `Failed to load sessions (${error.status})`
			});
			pushToast(`Failed to load sessions (${error.status}).`, 'error');
		} else {
			chatUiState.history = reduceSessionHistory(chatUiState.history, {
				type: 'sessions_load_error',
				error: 'Failed to load session history.'
			});
			pushToast('Failed to load session history.', 'error');
		}
	}
}

async function hydrateSessionTranscript(sessionId: string): Promise<void> {
	if (BACKEND_DISABLED) {
		currentSession.messages = [];
		taskStore.tasks.clear();
		taskStore.activeTaskId = null;
		chatUiState.history = reduceSessionHistory(chatUiState.history, {
			type: 'transcript_load_success',
			sessionId
		});
		return;
	}
	chatUiState.history = reduceSessionHistory(chatUiState.history, {
		type: 'transcript_load_start',
		sessionId
	});
	currentSession.messages = [];
	try {
		const transcriptMessages = await listSessionMessages(sessionId, 2000);
		if (currentSession.id !== sessionId) {
			return;
		}
		currentSession.messages = transcriptMessages;
		try {
			const sessionEvents = await listSessionEvents(sessionId, 4000);
			if (currentSession.id === sessionId) {
				hydrateMessageRuntimeEventsFromSessionEvents(sessionEvents);
				hydrateTaskStateFromEvents(sessionEvents);
			}
		} catch (eventsError) {
			console.warn('Failed to load session events:', eventsError);
			taskStore.tasks.clear();
			taskStore.activeTaskId = null;
			pushToast('Failed to load task/event history for this session.', 'warning');
		}
		chatUiState.history = reduceSessionHistory(chatUiState.history, {
			type: 'transcript_load_success',
			sessionId
		});
	} catch (error) {
		console.warn('Failed to load session messages:', error);
		if (currentSession.id !== sessionId) {
			return;
		}
		currentSession.messages = [];
		taskStore.tasks.clear();
		taskStore.activeTaskId = null;
		chatUiState.history = reduceSessionHistory(chatUiState.history, {
			type: 'transcript_load_error',
			sessionId,
			error: 'Unable to load transcript for this session.'
		});
		pushToast('Unable to load transcript for this session.', 'error');
	}
}

export async function selectSession(sessionId: string): Promise<void> {
	const selected = sessions.list.find((s) => s.id === sessionId);
	currentSession.id = sessionId;
	currentSession.name = selected?.name || `Session ${sessionId.slice(0, 8)}`;
	currentSession.activeAgent = null;
	currentSession.agentStatus = 'idle';
	currentSession.costUsd = 0;
	currentSession.tokensUsed = 0;
	currentSession.contextPct = 0;
	await hydrateSessionTranscript(sessionId);
	onModeRequest?.('chat');
	if (!BACKEND_DISABLED) {
		connectSocket(sessionId);
	}
}

export function handleNewChat(): void {
	resetLocalSessionState();
	if (!BACKEND_DISABLED) {
		connectSocket();
		void loadSessionsData();
	}
}

function handleSlashCommand(raw: string): boolean {
	const parsed = parseSlashCommand(raw);
	if (!parsed) return false;
	const { command, rawArgs: arg } = parsed;

	switch (command.toLowerCase()) {
		case 'new':
			handleNewChat();
			return true;
		case 'clear':
			currentSession.messages = [];
			return true;
		case 'sessions':
			onModeRequest?.('chat');
			return true;
		case 'agents':
			onModeRequest?.('agents');
			return true;
		case 'tasks':
			onModeRequest?.('tasks');
			return true;
		case 'timeline':
			onModeRequest?.('timeline');
			return true;
		case 'memory':
			onModeRequest?.('memory');
			return true;
		case 'config':
			onModeRequest?.('config');
			return true;
		case 'agent':
			if (!arg) {
				pushLocalAssistantNote('Usage: `/agent <name>` or `/agent clear`');
				return true;
			}
			if (arg === 'clear' || arg === 'none' || arg === 'auto') {
				chatUiState.pinnedAgent = null;
				pushLocalAssistantNote('Agent pin cleared. Routing returned to automatic mode.');
				return true;
			}
			const candidateAgent = arg.toLowerCase();
			if (!isKnownEnabledAgent(candidateAgent)) {
				pushLocalAssistantNote(`Unknown agent: \`${arg}\``);
				return true;
			}
			chatUiState.pinnedAgent = candidateAgent;
			applyPinnedAgentPreference(candidateAgent);
			pushLocalAssistantNote(`Pinned agent for next turns: \`${chatUiState.pinnedAgent}\``);
			return true;
		case 'model':
			if (!arg || arg === 'preferred' || arg === 'auto') {
				chatUiState.modelSelectionMode = 'preferred';
				currentSession.selectedModel = resolvePreferredModelId(
					modelStore.defaultModel,
					modelStore.models
				);
				pushLocalAssistantNote('Model selection reset to preferred/auto mode.');
				return true;
			}
			chatUiState.modelSelectionMode = 'manual';
			currentSession.selectedModel = arg;
			const targetAgent = chatUiState.pinnedAgent ?? chatUiState.lastRoutedAgent;
			if (targetAgent) {
				updateModelPreference(targetAgent, arg);
			}
			pushLocalAssistantNote(`Manual model override set: \`${arg}\``);
			return true;
		case 'dispatch':
			if (!arg) {
				pushLocalAssistantNote('Usage: `/dispatch <router|direct|parallel>`');
				return true;
			}
			if (arg !== 'router' && arg !== 'direct' && arg !== 'parallel') {
				pushLocalAssistantNote('Dispatch mode must be one of: `router`, `direct`, `parallel`.');
				return true;
			}
			chatUiState.dispatchMode = arg;
			pushLocalAssistantNote(`Dispatch mode set to \`${arg}\`.`);
			return true;
		case 'skill':
			if (!arg) {
				pushLocalAssistantNote('Usage: `/skill <name> [args]`');
				return true;
			}
			return false;
		case 'help':
			pushLocalAssistantNote(
				[
					'Available commands:',
					'- `/new`',
					'- `/clear`',
					'- `/sessions`',
					'- `/agents`',
					'- `/tasks`',
					'- `/timeline`',
					'- `/memory`',
					'- `/config`',
					'- `/agent <name|clear>`',
					'- `/model <id|preferred>`',
					'- `/dispatch <router|direct|parallel>`',
					'- `/skill <name> [args]`',
					'- `/help`'
				].join('\n')
			);
			return true;
		default:
			pushLocalAssistantNote(`Unknown command: \`/${command}\``);
			return true;
	}
}

function findLatestTaskForAgent(agent: string | null): Task | null {
	if (!agent) return null;
	const candidates = Array.from(taskStore.tasks.values())
		.filter((task) => task.agent === agent && task.status !== 'done' && task.result === undefined)
		.sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime());
	return candidates[0] ?? null;
}

function logEventToLatestTask(
	kind: TaskEvent['kind'],
	text: string,
	agent: string | null,
	callId?: string
): void {
	const task = findLatestTaskForAgent(agent);
	if (!task) return;
	appendTaskEvent(task.id, {
		kind,
		text,
		timestamp: new Date(),
		callId
	});
}

function attachMessageToTaskStream(message: ChatMessage): void {
	if (message.role !== 'assistant' || !message.agent) return;
	const task = findLatestTaskForAgent(message.agent);
	if (!task) return;
	if (!task.messages.some((m) => m.id === message.id)) {
		task.messages.push(message);
	}
}

function appendTaskEvent(taskId: string, event: TaskEvent): void {
	const task = taskStore.tasks.get(taskId);
	if (!task) return;
	if (!task.events) {
		task.events = [];
	}
	task.events.push(event);
}

function appendOrderedRunChunks(taskId: string, chunks: RunOutputChunk[]): void {
	for (const chunk of chunks) {
		if (chunk.content) {
			appendTaskEvent(taskId, {
				kind: 'run_output_chunk',
				timestamp: chunk.timestamp,
				text: chunk.content
			});
		}
		if (chunk.final) {
			appendTaskEvent(taskId, {
				kind: 'info',
				timestamp: chunk.timestamp,
				text: `Stream finalized (chunk ${chunk.chunkIndex})`
			});
		}
	}
}

function appendMissingChunkRanges(
	taskId: string,
	runId: string,
	missingRanges: Array<{ from: number; to: number }>,
	timestamp: Date
): void {
	for (const range of missingRanges) {
		const label = range.from === range.to ? `${range.from}` : `${range.from}-${range.to}`;
		appendTaskEvent(taskId, {
			kind: 'info',
			timestamp,
			text: `Missing streamed chunk(s) ${label} for run ${runId}`
		});
	}
}

function asString(value: unknown): string | null {
	return typeof value === 'string' && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function resolveEventAgent(payload: Record<string, unknown>): string | null {
	const raw = asString(payload.agent);
	return raw && isValidAgentName(raw) ? raw : null;
}

function findNearestAssistantMessageForEvent(
	agent: string | null,
	timestamp: Date
): ChatMessage | null {
	const assistants = currentSession.messages.filter(
		(message) => message.role === 'assistant' && (!agent || message.agent === agent)
	);
	if (assistants.length === 0) return null;

	let best: ChatMessage | null = null;
	let bestDelta = Number.POSITIVE_INFINITY;
	for (const candidate of assistants) {
		const delta = Math.abs(candidate.timestamp.getTime() - timestamp.getTime());
		if (delta < bestDelta) {
			best = candidate;
			bestDelta = delta;
		}
	}
	return best;
}

function toRuntimeEventFromSessionEvent(event: SessionEvent): Omit<ChatRuntimeEvent, 'id'> | null {
	const payload = event.payload ?? {};
	if (event.eventType === 'run_phase') {
		const phase = asString(payload['phase']) ?? 'phase';
		const summary = asString(payload['summary']) ?? phase;
		const phaseKind: ChatRuntimeEvent['kind'] =
			phase === 'planning' || phase === 'routing' || phase === 'queued' ? 'thinking' : 'phase';
		return {
			kind: phaseKind,
			summary: `${phase}: ${summary}`,
			timestamp: event.createdAt
		};
	}
	if (event.eventType === 'task_progress') {
		const summary = asString(payload['summary']) ?? 'Task update';
		return {
			kind: classifySummaryAsTodo(summary) ? 'todo' : 'reasoning',
			summary,
			timestamp: event.createdAt
		};
	}
	if (event.eventType === 'tool_start') {
		const tool = asString(payload['tool']) ?? 'tool';
		const detail = trimDetail(
			typeof payload['params'] === 'object' && payload['params'] !== null
				? JSON.stringify(payload['params'], null, 2)
				: undefined
		);
		return {
			kind: 'tool_start',
			summary: `Tool started: ${tool}`,
			timestamp: event.createdAt,
			callId: asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined,
			detail
		};
	}
	if (event.eventType === 'tool_result') {
		const status = asString(payload['status']) ?? 'success';
		const output = asString(payload['output']) ?? undefined;
		return {
			kind: 'tool_result',
			summary: `Tool ${status}`,
			timestamp: event.createdAt,
			callId: asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined,
			detail: trimDetail(output)
		};
	}
	if (event.eventType === 'tool_permission_decision') {
		const state = asString(payload['state']) ?? (payload['allowed'] === true ? 'allow' : 'deny');
		const tool = asString(payload['tool']) ?? 'tool';
		const reason = asString(payload['reason']) ?? undefined;
		return {
			kind: 'info',
			summary: `Permission ${state}: ${tool}`,
			timestamp: event.createdAt,
			detail: trimDetail(reason)
		};
	}
	if (event.eventType === 'confirm_request') {
		const tool = asString(payload['tool']) ?? 'tool';
		return {
			kind: 'confirm_request',
			summary: `Approval required for ${tool}`,
			timestamp: event.createdAt,
			callId: asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined
		};
	}
	if (event.eventType === 'run_complete' || event.eventType === 'task_complete') {
		const summary = asString(payload['summary']) ?? 'Run complete';
		const result = asString(payload['result']);
		return {
			kind: 'result',
			summary: result ? `${result}: ${summary}` : summary,
			timestamp: event.createdAt
		};
	}
	return null;
}

function hydrateMessageRuntimeEventsFromSessionEvents(events: SessionEvent[]): void {
	for (const event of events) {
		const runtimeEvent = toRuntimeEventFromSessionEvent(event);
		if (!runtimeEvent) continue;
		const agent = resolveEventAgent(event.payload ?? {});
		const targetMessage = findNearestAssistantMessageForEvent(agent, event.createdAt);
		if (!targetMessage) continue;
		appendRuntimeEventToMessage(targetMessage, runtimeEvent);
	}
}

function hydrateTaskStateFromEvents(events: SessionEvent[]): void {
	taskStore.tasks.clear();
	taskStore.activeTaskId = null;
	runOutputOrderer.resetAll();
	const turnToTask = new Map<string, string>();
	const runToTask = new Map<string, string>();
	const replayOrderer = new RunOutputOrderer();
	const replayRunToTask = new Map<string, string>();

	for (const event of events) {
		const payload = event.payload ?? {};
		const taskId = asString(payload['task_id']) ?? asString(payload['taskId']);
		const runId = asString(payload['run_id']) ?? asString(payload['runId']);
		if (!taskId) continue;
		const maybeAgent = asString(payload.agent);
		const agent = maybeAgent && isValidAgentName(maybeAgent) ? maybeAgent : 'general';

		if (event.eventType === 'task_start' || event.eventType === 'run_start') {
			if (!taskStore.tasks.has(taskId)) {
				addTask({
					id: taskId,
					agent,
					dispatchId:
						asString(payload['dispatch_id']) ?? asString(payload['dispatchId']) ?? undefined,
					runId: runId ?? undefined,
					description: asString(payload['description']) ?? '',
					status: 'thinking',
					phase: event.eventType === 'run_start' ? 'queued' : undefined,
					summary: '',
					costUsd: 0,
					startedAt: event.createdAt,
					completedAt: undefined,
					messages: [],
					sessionId: asString(payload['session_id']) ?? undefined,
					turnId: asString(payload['turn_id']) ?? event.turnId,
					events: []
				});
			}
			const turnId = asString(payload['turn_id']) ?? event.turnId;
			if (turnId) {
				turnToTask.set(turnId, taskId);
			}
			if (runId) {
				runToTask.set(runId, taskId);
				replayRunToTask.set(runId, taskId);
				replayOrderer.resetRun(runId);
			}
			continue;
		}

		let resolvedTaskId = taskId;
		if (!resolvedTaskId && runId) {
			resolvedTaskId = runToTask.get(runId) ?? '';
		}
		const task = taskStore.tasks.get(resolvedTaskId);
		if (!task) continue;

		if (event.eventType === 'task_progress') {
			const summary = asString(payload['summary']) ?? task.summary;
			const statusRaw = asString(payload['status']);
			const status: AgentStatus =
				statusRaw === 'idle' ||
				statusRaw === 'thinking' ||
				statusRaw === 'streaming' ||
				statusRaw === 'done' ||
				statusRaw === 'error'
					? statusRaw
					: task.status;
			updateTask(task.id, { summary, status });
			appendTaskEvent(task.id, {
				kind: 'task_progress',
				timestamp: event.createdAt,
				text: summary
			});
			continue;
		}

		if (event.eventType === 'run_phase') {
			const summary = asString(payload['summary']) ?? task.summary;
			const phaseRaw = asString(payload['phase']);
			const phase =
				phaseRaw === 'queued' ||
				phaseRaw === 'routing' ||
				phaseRaw === 'planning' ||
				phaseRaw === 'executing' ||
				phaseRaw === 'compacting' ||
				phaseRaw === 'done' ||
				phaseRaw === 'error'
					? phaseRaw
					: task.phase;
			const status: AgentStatus =
				phase === 'executing'
					? 'streaming'
					: phase === 'done'
						? 'done'
						: phase === 'error'
							? 'error'
							: 'thinking';
			updateTask(task.id, { summary, phase, status });
			appendTaskEvent(task.id, {
				kind: 'run_phase',
				timestamp: event.createdAt,
				text: `${phase}: ${summary}`
			});
			continue;
		}

		if (event.eventType === 'run_output_chunk') {
			const content = asString(payload['content']) ?? '';
			const chunkIndex = asNumber(payload['chunk_index']) ?? asNumber(payload['chunkIndex']);
			const final = payload['final'] === true;
			if (runId && chunkIndex !== null) {
				const ordered = replayOrderer.ingest({
					runId,
					taskId: task.id,
					chunkIndex,
					final,
					content,
					timestamp: event.createdAt
				});
				appendOrderedRunChunks(task.id, ordered);
			} else if (content) {
				appendTaskEvent(task.id, {
					kind: 'run_output_chunk',
					timestamp: event.createdAt,
					text: content
				});
			}
			continue;
		}

		if (event.eventType === 'task_complete' || event.eventType === 'run_complete') {
			if (runId) {
				const flushed = replayOrderer.flushRun(runId);
				appendOrderedRunChunks(task.id, flushed.chunks);
				appendMissingChunkRanges(task.id, runId, flushed.missingRanges, event.createdAt);
				replayOrderer.resetRun(runId);
			}
			updateTask(task.id, {
				status: 'done',
				phase: event.eventType === 'run_complete' ? 'done' : task.phase,
				result:
					asString(payload['result']) === 'error'
						? 'error'
						: asString(payload['result']) === 'success'
							? 'success'
							: task.result,
				summary: asString(payload['summary']) ?? task.summary,
				costUsd: asNumber(payload['cost_usd']) ?? task.costUsd,
				completedAt: event.createdAt
			});
			appendTaskEvent(task.id, {
				kind: 'info',
				timestamp: event.createdAt,
				text: asString(payload['summary']) ?? 'Task completed'
			});
		}
	}

	for (const [runId, taskId] of replayRunToTask.entries()) {
		const flushed = replayOrderer.flushRun(runId);
		if (flushed.chunks.length === 0 && flushed.missingRanges.length === 0) continue;
		const tailTimestamp = flushed.chunks.at(-1)?.timestamp ?? new Date();
		appendOrderedRunChunks(taskId, flushed.chunks);
		appendMissingChunkRanges(taskId, runId, flushed.missingRanges, tailTimestamp);
		replayOrderer.resetRun(runId);
	}

	for (const event of events) {
		const payload = event.payload ?? {};
		const eventType = event.eventType;
		if (
			eventType !== 'tool_start' &&
			eventType !== 'tool_result' &&
			eventType !== 'tool_permission_decision' &&
			eventType !== 'confirm_request'
		) {
			continue;
		}

		const taskId =
			(asString(payload['task_id']) ?? asString(payload['taskId'])) ||
			((asString(payload['run_id']) ?? asString(payload['runId']))
				? runToTask.get(asString(payload['run_id']) ?? asString(payload['runId']) ?? '') ?? null
				: null) ||
			(event.turnId ? turnToTask.get(event.turnId) ?? null : null);
		if (!taskId) continue;

		if (eventType === 'tool_start') {
			const tool = asString(payload['tool']) ?? 'tool';
			const callId = asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined;
			appendTaskEvent(taskId, {
				kind: 'tool_start',
				timestamp: event.createdAt,
				text: `Tool start: ${tool}`,
				callId
			});
			continue;
		}
		if (eventType === 'tool_result') {
			const status = asString(payload.status) ?? 'success';
			const callId = asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined;
			appendTaskEvent(taskId, {
				kind: 'tool_result',
				timestamp: event.createdAt,
				text: `Tool result (${status})`,
				callId
			});
			continue;
		}
		if (eventType === 'tool_permission_decision') {
			const state = asString(payload['state']) ?? (payload['allowed'] === true ? 'allow' : 'deny');
			const tool = asString(payload['tool']) ?? 'tool';
			const callId = asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined;
			appendTaskEvent(taskId, {
				kind: 'tool_permission_decision',
				timestamp: event.createdAt,
				text: `Permission ${state}: ${tool}`,
				callId
			});
			continue;
		}
		const callId = asString(payload['call_id']) ?? asString(payload['callId']) ?? undefined;
		appendTaskEvent(taskId, {
			kind: 'confirm_request',
			timestamp: event.createdAt,
			text: `Confirmation requested: ${asString(payload['tool']) ?? 'tool'}`,
			callId
		});
	}

	if (!taskStore.activeTaskId) {
		const mostRecent = Array.from(taskStore.tasks.values()).sort(
			(a, b) => b.startedAt.getTime() - a.startedAt.getTime()
		)[0];
		taskStore.activeTaskId = mostRecent?.id ?? null;
	}
}

function nextRuntimeEventId(): string {
	runtimeEventSeq += 1;
	return `runtime-${runtimeEventSeq}`;
}

function trimDetail(value: string | undefined, limit = 800): string | undefined {
	if (!value) return undefined;
	const trimmed = value.trim();
	if (trimmed.length <= limit) return trimmed;
	return `${trimmed.slice(0, limit)}...`;
}

function classifySummaryAsTodo(summary: string): boolean {
	if (!summary) return false;
	return /\btodo\b|\bnext steps?\b|\[ \]|\bchecklist\b/i.test(summary);
}

function appendRuntimeEventToMessage(
	message: ChatMessage,
	event: Omit<ChatRuntimeEvent, 'id'>
): void {
	if (!message.runtimeEvents) {
		message.runtimeEvents = [];
	}
	const events = message.runtimeEvents;
	const signature = `${event.kind}|${event.summary}|${event.callId ?? ''}`;
	const previous = events[events.length - 1];
	if (previous) {
		const previousSignature = `${previous.kind}|${previous.summary}|${previous.callId ?? ''}`;
		if (signature === previousSignature) {
			previous.timestamp = event.timestamp;
			if (event.detail) {
				previous.detail = event.detail;
			}
			return;
		}
	}
	events.push({
		id: nextRuntimeEventId(),
		...event
	});
	if (events.length > 80) {
		events.splice(0, events.length - 80);
	}
}

function getOrCreateAssistantMessage(
	agentOverride?: string | null,
	modelOverride?: string
): ChatMessage {
	const msgs = currentSession.messages;
	const last = msgs[msgs.length - 1];
	const agentForMessage =
		agentOverride ?? chatUiState.lastRoutedAgent ?? currentSession.activeAgent ?? undefined;
	const modelForMessage = modelOverride ?? chatUiState.lastRoutedModel ?? undefined;
	if (last?.role === 'assistant' && last.agent === agentForMessage) {
		return last;
	}
	const newMsg: ChatMessage = {
		id: uuid(),
		role: 'assistant',
		content: '',
		agent: agentForMessage,
		model: modelForMessage,
		timestamp: new Date(),
		toolCalls: []
	};
	msgs.push(newMsg);
	attachMessageToTaskStream(newMsg);
	return newMsg;
}

function appendRuntimeEventToAssistantMessage(
	event: Omit<ChatRuntimeEvent, 'id'> & {
		agent?: string | null;
		model?: string;
	}
): void {
	const message = getOrCreateAssistantMessage(event.agent, event.model);
	appendRuntimeEventToMessage(message, {
		kind: event.kind,
		summary: event.summary,
		timestamp: event.timestamp,
		detail: event.detail,
		callId: event.callId
	});
	attachMessageToTaskStream(message);
}

function isCurrentSessionMessage(sessionId: string | null | undefined): boolean {
	if (!currentSession.id) return true;
	if (!sessionId) return false;
	return sessionId === currentSession.id;
}

function hasActiveTasksInSession(sessionId: string | null | undefined): boolean {
	if (!sessionId) {
		return Array.from(taskStore.tasks.values()).some(
			(task) => task.status !== 'done' && task.result === undefined
		);
	}
	return Array.from(taskStore.tasks.values()).some(
		(task) =>
			task.sessionId === sessionId && task.status !== 'done' && task.result === undefined
	);
}

function handleMessage(msg: ServerMessage): void {
	switch (msg.type) {
		case 'routing':
			chatUiState.lastRoutedAgent = isValidAgentName(msg.agent) ? msg.agent : null;
			chatUiState.lastRoutedModel = msg.model;
			currentSession.activeAgent = chatUiState.lastRoutedAgent;
			appendRuntimeEventToAssistantMessage({
				agent: chatUiState.lastRoutedAgent,
				model: msg.model,
				kind: 'thinking',
				summary: `Routing to ${msg.agent} (${msg.model})`,
				timestamp: new Date()
			});
			if (chatUiState.modelSelectionMode === 'preferred') {
				currentSession.selectedModel = msg.model;
			}
			currentSession.agentStatus = 'thinking';
			break;
		case 'agent_status':
			currentSession.agentStatus = msg.status;
			break;
		case 'text': {
			const validAgent =
				msg.agent && isValidAgentName(msg.agent)
					? msg.agent
					: (chatUiState.lastRoutedAgent ?? currentSession.activeAgent ?? undefined);
			const modelForMessage = msg.model || chatUiState.lastRoutedModel || undefined;
			const lastMsg = currentSession.messages[currentSession.messages.length - 1];
			if (lastMsg?.role === 'assistant' && lastMsg.agent === validAgent) {
				lastMsg.content += msg.content;
				if (!lastMsg.model && modelForMessage) {
					lastMsg.model = modelForMessage;
				}
				attachMessageToTaskStream(lastMsg);
			} else {
				const newMsg: ChatMessage = {
					id: uuid(),
					role: 'assistant',
					content: msg.content,
					agent: validAgent,
					model: modelForMessage,
					timestamp: new Date()
				};
				currentSession.messages.push(newMsg);
				attachMessageToTaskStream(newMsg);
			}
			if (validAgent) {
				currentSession.activeAgent = validAgent;
			}
			currentSession.agentStatus = 'streaming';
			break;
		}
		case 'tool_start': {
			const eventAgent = chatUiState.lastRoutedAgent ?? currentSession.activeAgent;
			const toolCall: ToolCall = {
				callId: msg.call_id,
				tool: msg.tool,
				params: msg.params,
				status: 'running'
			};
			pendingToolCalls.calls.set(msg.call_id, toolCall);
			const assistantMsg = getOrCreateAssistantMessage(eventAgent);
			if (!assistantMsg.toolCalls) {
				assistantMsg.toolCalls = [];
			}
			assistantMsg.toolCalls.push(toolCall);
			appendRuntimeEventToMessage(assistantMsg, {
				kind: 'tool_start',
				summary: `Tool started: ${msg.tool}`,
				detail: trimDetail(JSON.stringify(msg.params ?? {}, null, 2)),
				timestamp: new Date(),
				callId: msg.call_id
			});
			logEventToLatestTask(
				'tool_start',
				`Tool started: ${msg.tool}`,
				eventAgent,
				msg.call_id
			);
			break;
		}
		case 'tool_result': {
			const pending = pendingToolCalls.calls.get(msg.call_id);
			if (pending) {
				pending.output = msg.output;
				pending.durationMs = msg.duration_ms;
				pending.status = msg.status;
				pendingToolCalls.calls.delete(msg.call_id);
			}
			let matchedMessage: ChatMessage | null = null;
			for (const m of currentSession.messages) {
				if (m.toolCalls) {
					const tc = m.toolCalls.find((t) => t.callId === msg.call_id);
					if (tc) {
						tc.output = msg.output;
						tc.durationMs = msg.duration_ms;
						tc.status = msg.status;
						matchedMessage = m;
						break;
					}
				}
			}
			if (matchedMessage) {
				appendRuntimeEventToMessage(matchedMessage, {
					kind: 'tool_result',
					summary: `Tool ${msg.status}: ${pending?.tool ?? msg.call_id}`,
					detail: trimDetail(msg.output),
					timestamp: new Date(),
					callId: msg.call_id
				});
			} else {
				appendRuntimeEventToAssistantMessage({
					agent: chatUiState.lastRoutedAgent ?? currentSession.activeAgent,
					kind: 'tool_result',
					summary: `Tool ${msg.status}: ${msg.call_id}`,
					detail: trimDetail(msg.output),
					timestamp: new Date(),
					callId: msg.call_id
				});
			}
			logEventToLatestTask(
				'tool_result',
				`Tool ${msg.status}: ${msg.call_id}`,
				chatUiState.lastRoutedAgent ?? currentSession.activeAgent,
				msg.call_id
			);
			break;
		}
		case 'tool_permission_decision': {
			const permissionAgent =
				(msg.agent && isValidAgentName(msg.agent)
					? msg.agent
					: chatUiState.lastRoutedAgent ?? currentSession.activeAgent) ?? null;
			const state = msg.state ?? (msg.allowed ? 'allow' : 'deny');
			const detail = [msg.scope, msg.reason].filter((part) => typeof part === 'string' && part.length > 0);
			appendRuntimeEventToAssistantMessage({
				agent: permissionAgent,
				kind: 'info',
				summary: `Permission ${state}: ${msg.tool}`,
				timestamp: new Date(),
				detail: detail.length > 0 ? detail.join(' - ') : undefined
			});
			logEventToLatestTask(
				'tool_permission_decision',
				`Permission ${state}: ${msg.tool}`,
				permissionAgent
			);
			break;
		}
		case 'confirm_request':
			activeConfirm.request = {
				callId: msg.call_id,
				tool: msg.tool,
				params: msg.params,
				timeoutS: msg.timeout_s,
				createdAt: new Date()
			};
			appendRuntimeEventToAssistantMessage({
				agent: chatUiState.lastRoutedAgent ?? currentSession.activeAgent,
				kind: 'confirm_request',
				summary: `Approval required for ${msg.tool}`,
				detail: trimDetail(JSON.stringify(msg.params ?? {}, null, 2)),
				timestamp: new Date(),
				callId: msg.call_id
			});
			logEventToLatestTask(
				'confirm_request',
				`Approval required for ${msg.tool}`,
				chatUiState.lastRoutedAgent ?? currentSession.activeAgent,
				msg.call_id
			);
			break;
		case 'dispatch_start':
			if (
				isCurrentSessionMessage(msg.session_id) &&
				msg.target_agents.length > 0 &&
				isValidAgentName(msg.target_agents[0])
			) {
				currentSession.activeAgent = msg.target_agents[0];
			}
			if (isCurrentSessionMessage(msg.session_id)) {
				currentSession.agentStatus = 'thinking';
			}
			break;
		case 'run_start': {
			const taskId = msg.task_id || msg.run_id;
			const agent = isValidAgentName(msg.agent) ? msg.agent : 'general';
			appendRuntimeEventToAssistantMessage({
				agent,
				model: msg.model,
				kind: 'thinking',
				summary: `Run started (${msg.run_id})`,
				timestamp: new Date()
			});
			runOutputOrderer.resetRun(msg.run_id);
			if (isCurrentSessionMessage(msg.session_id)) {
				currentSession.activeAgent = agent;
				currentSession.agentStatus = 'thinking';
			}
			if (!taskStore.tasks.has(taskId)) {
				addTask({
					id: taskId,
					agent,
					dispatchId: msg.dispatch_id,
					runId: msg.run_id,
					description: 'Agent run',
					status: 'thinking',
					phase: 'queued',
					summary: '',
					costUsd: 0,
					startedAt: new Date(),
					messages: [],
					sessionId: msg.session_id,
					turnId: msg.turn_id,
					events: []
				});
			}
			if (!taskStore.activeTaskId) {
				taskStore.activeTaskId = taskId;
			}
			break;
		}
		case 'run_phase': {
			const taskId = msg.task_id || msg.run_id;
			const status: AgentStatus =
				msg.phase === 'executing'
					? 'streaming'
					: msg.phase === 'done'
						? 'done'
						: msg.phase === 'error'
							? 'error'
							: 'thinking';
			const phaseAgent = isValidAgentName(msg.agent) ? msg.agent : null;
			appendRuntimeEventToAssistantMessage({
				agent: phaseAgent,
				kind:
					msg.phase === 'planning' || msg.phase === 'routing' || msg.phase === 'queued'
						? 'thinking'
						: msg.phase === 'done' || msg.phase === 'error'
							? 'result'
							: 'phase',
				summary: `${msg.phase}: ${msg.summary}`,
				timestamp: new Date()
			});
			if (phaseAgent && isCurrentSessionMessage(msg.session_id)) {
				currentSession.activeAgent = phaseAgent;
			}
			if (isCurrentSessionMessage(msg.session_id)) {
				currentSession.agentStatus = status;
			}
			updateTask(taskId, { status, phase: msg.phase, summary: msg.summary });
			appendTaskEvent(taskId, {
				kind: 'run_phase',
				timestamp: new Date(),
				text: `${msg.phase}: ${msg.summary}`
			});
			break;
		}
		case 'run_output_chunk': {
			const taskId = msg.task_id || msg.run_id;
			const ordered = runOutputOrderer.ingest({
				runId: msg.run_id,
				taskId,
				chunkIndex: msg.chunk_index,
				final: msg.final,
				content: msg.content,
				timestamp: new Date()
			});
			appendOrderedRunChunks(taskId, ordered);
			break;
		}
		case 'run_complete': {
			const taskId = msg.task_id || msg.run_id;
			const flushed = runOutputOrderer.flushRun(msg.run_id);
			appendOrderedRunChunks(taskId, flushed.chunks);
			appendMissingChunkRanges(taskId, msg.run_id, flushed.missingRanges, new Date());
			runOutputOrderer.resetRun(msg.run_id);
			updateTask(taskId, {
				status: 'done',
				phase: 'done',
				result: msg.result,
				summary: msg.summary,
				costUsd: msg.cost_usd,
				completedAt: new Date()
			});
			if (
				isCurrentSessionMessage(msg.session_id) &&
				!hasActiveTasksInSession(msg.session_id)
			) {
				currentSession.agentStatus = msg.result === 'error' ? 'error' : 'done';
			}
			appendRuntimeEventToAssistantMessage({
				agent: isValidAgentName(msg.agent) ? msg.agent : null,
				kind: 'result',
				summary: msg.summary,
				timestamp: new Date(),
				detail:
					msg.tokens_used !== undefined
						? `cost=$${msg.cost_usd.toFixed(4)}, tokens=${msg.tokens_used}`
						: `cost=$${msg.cost_usd.toFixed(4)}`
			});
			appendTaskEvent(taskId, {
				kind: 'info',
				timestamp: new Date(),
				text: msg.summary
			});
			break;
		}
		case 'dispatch_complete':
			if (isCurrentSessionMessage(msg.session_id)) {
				currentSession.agentStatus = msg.status === 'error' ? 'error' : 'done';
			}
			break;
		case 'done':
			currentSession.id = msg.session_id;
			currentSession.costUsd = msg.cost_usd;
			currentSession.tokensUsed = msg.tokens_used;
			currentSession.contextPct = msg.context_pct;
			currentSession.agentStatus = 'done';
			appendRuntimeEventToAssistantMessage({
				agent: currentSession.activeAgent,
				kind: 'result',
				summary: `Turn complete`,
				timestamp: new Date(),
				detail: `cost=$${msg.cost_usd.toFixed(4)}, tokens=${msg.tokens_used}, context=${msg.context_pct.toFixed(1)}%`
			});
			void loadSessionsData();
			break;
		case 'error': {
			currentSession.agentStatus = 'error';
			let content = msg.message;
			if (msg.error === 'model_unavailable') {
				const failedModelId = msg.model || currentSession.selectedModel || '';
				const fallback = resolveFallbackModelId({
					failedModelId,
					defaultModelId: modelStore.defaultModel,
					lastRoutedModelId: chatUiState.lastRoutedModel,
					models: modelStore.models
				});
				if (fallback) {
					chatUiState.modelSelectionMode = 'manual';
					currentSession.selectedModel = fallback;
					content = `${msg.message}. Frontend selected fallback model \`${fallback}\`. Resend to retry.`;
				} else {
					content = `${msg.message}. No available frontend fallback model.`;
				}
			}
			if (msg.error === 'model_capability_mismatch') {
				const suggested = msg.suggested_model;
				if (suggested) {
					chatUiState.modelSelectionMode = 'manual';
					currentSession.selectedModel = suggested;
					content = `${msg.message}. Frontend selected \`${suggested}\`; resend to retry.`;
				}
			}
			appendRuntimeEventToAssistantMessage({
				agent: chatUiState.lastRoutedAgent ?? currentSession.activeAgent,
				model: msg.model,
				kind: 'result',
				summary: `Error: ${content}`,
				timestamp: new Date()
			});
			currentSession.messages.push({
				id: uuid(),
				role: 'assistant',
				content: `**Error:** ${content}`,
				timestamp: new Date(),
				isError: true
			});
			pushToast(content, 'error');
			break;
		}
		case 'init':
			modelStore.models = msg.models;
			modelStore.defaultModel = msg.default_model;
			agentStore.agents = msg.agents;
			agentStore.defaultAgent = msg.default_agent;
			const preferredModel = resolvePreferredModelId(modelStore.defaultModel, modelStore.models);
			const selectedStillAvailable = modelStore.models.some(
				(model) => model.id === currentSession.selectedModel && model.available
			);
			if (!currentSession.selectedModel || !selectedStillAvailable) {
				currentSession.selectedModel = preferredModel;
			}
			if (msg.session_id) {
				currentSession.id = msg.session_id;
			}
			if (msg.session_name) {
				currentSession.name = msg.session_name;
			}
			break;
		case 'task_start': {
			const agent = isValidAgentName(msg.agent) ? msg.agent : 'general';
			appendRuntimeEventToAssistantMessage({
				agent,
				kind: classifySummaryAsTodo(msg.description) ? 'todo' : 'reasoning',
				summary: msg.description || 'Task started',
				timestamp: new Date()
			});
			if (isCurrentSessionMessage(msg.session_id)) {
				currentSession.activeAgent = agent;
				currentSession.agentStatus = 'thinking';
			}
			addTask({
				id: msg.task_id,
				agent,
				description: msg.description,
				status: 'thinking',
				summary: '',
				costUsd: 0,
				startedAt: new Date(),
				messages: [],
				sessionId: msg.session_id,
				turnId: msg.turn_id,
				events: []
			});
			if (!taskStore.activeTaskId) {
				taskStore.activeTaskId = msg.task_id;
			}
			break;
		}
		case 'task_progress': {
			const status = msg.status as AgentStatus;
			const taskSessionId = msg.session_id ?? taskStore.tasks.get(msg.task_id)?.sessionId ?? null;
			const progressAgent = isValidAgentName(msg.agent) ? msg.agent : null;
			appendRuntimeEventToAssistantMessage({
				agent: progressAgent,
				kind: classifySummaryAsTodo(msg.summary) ? 'todo' : 'reasoning',
				summary: msg.summary,
				timestamp: new Date()
			});
			if (progressAgent && isCurrentSessionMessage(taskSessionId)) {
				currentSession.activeAgent = progressAgent;
			}
			if (isCurrentSessionMessage(taskSessionId)) {
				currentSession.agentStatus = status;
			}
			updateTask(msg.task_id, {
				status,
				summary: msg.summary
			});
			appendTaskEvent(msg.task_id, {
				kind: 'task_progress',
				timestamp: new Date(),
				text: msg.summary
			});
			break;
		}
		case 'task_complete':
			appendRuntimeEventToAssistantMessage({
				agent: isValidAgentName(msg.agent) ? msg.agent : null,
				kind: 'result',
				summary: msg.summary,
				timestamp: new Date(),
				detail:
					msg.cost_usd > 0 ? `result=${msg.result}, cost=$${msg.cost_usd.toFixed(4)}` : `result=${msg.result}`
			});
			updateTask(msg.task_id, {
				status: 'done',
				result: msg.result,
				summary: msg.summary,
				costUsd: msg.cost_usd,
				completedAt: new Date()
			});
			{
				const taskSessionId = msg.session_id ?? taskStore.tasks.get(msg.task_id)?.sessionId ?? null;
				if (
					isCurrentSessionMessage(taskSessionId) &&
					!hasActiveTasksInSession(taskSessionId)
				) {
					currentSession.agentStatus = msg.result === 'error' ? 'error' : 'done';
				}
			}
			appendTaskEvent(msg.task_id, {
				kind: 'info',
				timestamp: new Date(),
				text: msg.summary
			});
			break;
		default:
			break;
	}
}

export function sendMessage(rawMessage: string): void {
	if (BACKEND_DISABLED) {
		pushToast('Backend is disabled in this run; send is unavailable.', 'warning', {
			dedupeKey: 'backend-disabled-send'
		});
		return;
	}
	if (!client) return;
	if (handleSlashCommand(rawMessage)) return;
	ensureModelPreferencesLoaded();

	const parsed = parseAgentMention(rawMessage, isKnownEnabledAgent);
	const outgoingMessage = parsed.message.trim();
	if (!outgoingMessage) return;

	currentSession.messages.push({
		id: uuid(),
		role: 'user',
		content: rawMessage,
		timestamp: new Date()
	});

	let targetAgent = parsed.targetAgent ?? chatUiState.pinnedAgent ?? undefined;
	let targetAgents = parsed.targetAgents ? [...parsed.targetAgents] : undefined;
	let dispatchMode: DispatchMode = chatUiState.dispatchMode;

	if (!targetAgent && !targetAgents) {
		if (chatUiState.sendToAllRecipients) {
			targetAgents = ['@all'];
			dispatchMode = 'parallel';
		} else if (chatUiState.selectedRecipients.length > 0) {
			if (chatUiState.selectedRecipients.length === 1 && dispatchMode !== 'parallel') {
				targetAgent = chatUiState.selectedRecipients[0] as string;
				if (dispatchMode === 'router') {
					dispatchMode = 'direct';
				}
			} else {
				targetAgents = [...chatUiState.selectedRecipients];
				if (dispatchMode === 'router') {
					dispatchMode = 'parallel';
				}
			}
		}
	}

	if (targetAgent && dispatchMode === 'router') {
		dispatchMode = 'direct';
	}

	const slashCommand = parseSlashCommand(outgoingMessage);
	const requiresTools = slashCommand?.command.toLowerCase() === 'skill';
	let modelOverride: string | undefined;
	if (chatUiState.modelSelectionMode === 'manual' && currentSession.selectedModel) {
		modelOverride = currentSession.selectedModel;
	} else {
		const preferredForAgent = preferredModelForAgent(
			(targetAgent ?? (targetAgents?.[0] as string | undefined) ?? null),
			chatUiState.modelPreferences
		);
		if (preferredForAgent) {
			modelOverride = preferredForAgent;
			currentSession.selectedModel = preferredForAgent;
		}
	}
	client.sendChat(
		outgoingMessage,
		modelOverride,
		targetAgent,
		requiresTools,
		targetAgents,
		dispatchMode
	);
}

export function setModelSelection(id: string): void {
	if (id === '__preferred__') {
		chatUiState.modelSelectionMode = 'preferred';
		currentSession.selectedModel = resolvePreferredModelId(modelStore.defaultModel, modelStore.models);
		return;
	}
	chatUiState.modelSelectionMode = 'manual';
	currentSession.selectedModel = id;
	const targetAgent = chatUiState.pinnedAgent ?? chatUiState.lastRoutedAgent;
	if (targetAgent) {
		updateModelPreference(targetAgent, id);
	}
}

export function clearPinnedAgent(): void {
	chatUiState.pinnedAgent = null;
}

export function setDispatchMode(mode: DispatchMode): void {
	chatUiState.dispatchMode = mode;
}

export function setComposerRecipients(recipients: string[], sendToAll: boolean): void {
	chatUiState.selectedRecipients = recipients;
	chatUiState.sendToAllRecipients = sendToAll;
}

export function interrupt(): void {
	client?.sendInterrupt();
}

export function respondToConfirm(callId: string, approved: boolean): void {
	if (!client) return;
	client.sendConfirm(callId, approved);
	activeConfirm.request = null;
}

export async function renameSessionEntry(sessionId: string, name: string): Promise<void> {
	const trimmed = name.trim();
	if (!trimmed) return;
	const session = sessions.list.find((s) => s.id === sessionId);
	const previousName = session?.name;
	if (session) {
		session.name = trimmed;
	}
	if (currentSession.id === sessionId) {
		currentSession.name = trimmed;
	}
	try {
		await renameSession(sessionId, trimmed);
	} catch (error) {
		if (session) {
			session.name = previousName;
		}
		if (currentSession.id === sessionId) {
			currentSession.name = previousName || 'Huginn';
		}
		const status = error instanceof ApiError ? ` (${error.status})` : '';
		pushLocalAssistantNote(`Failed to rename session${status}.`);
		pushToast(`Failed to rename session${status}.`, 'error');
	}
}

export async function deleteSessionEntry(sessionId: string): Promise<void> {
	const previous = sessions.list.slice();
	const deletingCurrent = currentSession.id === sessionId;
	sessions.list = sessions.list.filter((s) => s.id !== sessionId);
	try {
		await deleteSession(sessionId);
		if (deletingCurrent) {
			handleNewChat();
		}
	} catch (error) {
		sessions.list = previous;
		const status = error instanceof ApiError ? ` (${error.status})` : '';
		pushLocalAssistantNote(`Failed to delete session${status}.`);
		pushToast(`Failed to delete session${status}.`, 'error');
	}
}

export function retrySessionListLoad(): void {
	void loadSessionsData();
}

export async function retryCurrentTranscriptLoad(): Promise<void> {
	if (!currentSession.id) return;
	await hydrateSessionTranscript(currentSession.id);
}

export function startChatSession(): void {
	ensureModelPreferencesLoaded();
	if (BACKEND_DISABLED) {
		connectionStatus.value = 'disconnected';
		currentSession.agentStatus = 'idle';
		return;
	}
	void loadSessionsData();
	connectSocket();
}

export function stopChatSession(): void {
	client?.disconnect();
}

export function reconnectChatSession(): void {
	ensureModelPreferencesLoaded();
	if (BACKEND_DISABLED) {
		return;
	}
	connectSocket(currentSession.id ?? undefined);
}
