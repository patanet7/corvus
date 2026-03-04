import type { ChatMessage, Session, SessionEvent } from '$lib/types';
import { isValidAgentName } from '$lib/types';

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

interface ApiSessionMessage {
	id: number;
	session_id: string;
	role: 'user' | 'assistant';
	content: string;
	agent?: string | null;
	model?: string | null;
	created_at: string;
}

interface ApiSessionEvent {
	id: number;
	session_id: string;
	turn_id?: string | null;
	event_type: string;
	payload: Record<string, unknown>;
	created_at: string;
}

export class ApiError extends Error {
	status: number;

	constructor(message: string, status: number) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
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

function toChatMessage(msg: ApiSessionMessage): ChatMessage {
	const agent = msg.agent && isValidAgentName(msg.agent) ? msg.agent : undefined;
	return {
		id: `${msg.session_id}-${msg.id}`,
		role: msg.role,
		content: msg.content,
		agent,
		model: msg.model ?? undefined,
		timestamp: new Date(msg.created_at)
	};
}

function toSessionEvent(event: ApiSessionEvent): SessionEvent {
	return {
		id: event.id,
		sessionId: event.session_id,
		turnId: event.turn_id ?? undefined,
		eventType: event.event_type,
		payload: event.payload ?? {},
		createdAt: new Date(event.created_at)
	};
}

export async function listSessions(limit = 50): Promise<Session[]> {
	const response = await fetch(`/api/sessions?limit=${limit}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load sessions (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiSession[];
	return body.map(toSession);
}

export async function listSessionMessages(sessionId: string, limit = 2000): Promise<ChatMessage[]> {
	const response = await fetch(`/api/sessions/${sessionId}/messages?limit=${limit}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load session messages (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiSessionMessage[];
	return body.map(toChatMessage);
}

export async function listSessionEvents(sessionId: string, limit = 2000): Promise<SessionEvent[]> {
	const response = await fetch(`/api/sessions/${sessionId}/events?limit=${limit}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load session events (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiSessionEvent[];
	return body.map(toSessionEvent);
}

export async function renameSession(sessionId: string, name: string): Promise<void> {
	const response = await fetch(`/api/sessions/${sessionId}`, {
		method: 'PATCH',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({ name })
	});
	if (!response.ok) {
		throw new ApiError(`Failed to rename session (${response.status})`, response.status);
	}
}

export async function deleteSession(sessionId: string): Promise<void> {
	const response = await fetch(`/api/sessions/${sessionId}`, {
		method: 'DELETE'
	});
	if (!response.ok) {
		throw new ApiError(`Failed to delete session (${response.status})`, response.status);
	}
}
