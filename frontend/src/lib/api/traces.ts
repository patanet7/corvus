import type { TraceEvent, TraceFilterOptions } from '$lib/types';
import { ApiError } from '$lib/api/sessions';

interface ApiTraceEvent {
	id: number;
	source_app: string;
	session_id: string;
	dispatch_id?: string | null;
	run_id?: string | null;
	turn_id?: string | null;
	hook_event_type: string;
	payload?: Record<string, unknown>;
	summary?: string | null;
	model_name?: string | null;
	timestamp: string;
}

interface ApiTraceFilterOptions {
	source_apps?: string[];
	session_ids?: string[];
	hook_event_types?: string[];
}

export interface TraceQuery {
	limit?: number;
	offset?: number;
	sourceApps?: string[];
	sessionIds?: string[];
	dispatchId?: string;
	runId?: string;
	hookEventTypes?: string[];
}

function toTraceEvent(raw: ApiTraceEvent): TraceEvent {
	return {
		id: raw.id,
		sourceApp: raw.source_app,
		sessionId: raw.session_id,
		dispatchId: raw.dispatch_id ?? undefined,
		runId: raw.run_id ?? undefined,
		turnId: raw.turn_id ?? undefined,
		hookEventType: raw.hook_event_type,
		payload: raw.payload ?? {},
		summary: raw.summary ?? undefined,
		modelName: raw.model_name ?? undefined,
		timestamp: new Date(raw.timestamp)
	};
}

function toTraceFilterOptions(raw: ApiTraceFilterOptions): TraceFilterOptions {
	return {
		sourceApps: raw.source_apps ?? [],
		sessionIds: raw.session_ids ?? [],
		hookEventTypes: raw.hook_event_types ?? []
	};
}

function appendArrayParam(params: URLSearchParams, key: string, values?: string[]): void {
	if (!values || values.length === 0) return;
	for (const value of values) {
		if (!value) continue;
		params.append(key, value);
	}
}

function buildTraceQuery(query: TraceQuery): string {
	const params = new URLSearchParams();
	if (query.limit !== undefined) params.set('limit', String(query.limit));
	if (query.offset !== undefined) params.set('offset', String(query.offset));
	appendArrayParam(params, 'source_app', query.sourceApps);
	appendArrayParam(params, 'session_id', query.sessionIds);
	appendArrayParam(params, 'hook_event_type', query.hookEventTypes);
	if (query.dispatchId) params.set('dispatch_id', query.dispatchId);
	if (query.runId) params.set('run_id', query.runId);
	const encoded = params.toString();
	return encoded ? `?${encoded}` : '';
}

export async function listRecentTraces(query: TraceQuery = {}): Promise<TraceEvent[]> {
	const response = await fetch(`/api/traces/recent${buildTraceQuery(query)}`);
	if (!response.ok) {
		throw new ApiError(`Failed to load traces (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiTraceEvent[];
	return body.map(toTraceEvent);
}

export async function listSessionTraces(
	sessionId: string,
	query: Omit<TraceQuery, 'sessionIds' | 'dispatchId' | 'runId' | 'sourceApps'> = {}
): Promise<TraceEvent[]> {
	const params = new URLSearchParams();
	if (query.limit !== undefined) params.set('limit', String(query.limit));
	if (query.offset !== undefined) params.set('offset', String(query.offset));
	appendArrayParam(params, 'hook_event_type', query.hookEventTypes);
	const response = await fetch(
		`/api/sessions/${sessionId}/traces${params.toString() ? `?${params.toString()}` : ''}`
	);
	if (!response.ok) {
		throw new ApiError(`Failed to load session traces (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiTraceEvent[];
	return body.map(toTraceEvent);
}

export async function getTraceFilterOptions(): Promise<TraceFilterOptions> {
	const response = await fetch('/api/traces/filter-options');
	if (!response.ok) {
		throw new ApiError(`Failed to load trace filters (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiTraceFilterOptions;
	return toTraceFilterOptions(body);
}
