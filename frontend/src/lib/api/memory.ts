import { ApiError } from '$lib/api/sessions';

export interface MemoryAgentInfo {
	id: string;
	label: string;
	memoryDomain: string;
	canWrite: boolean;
	canReadShared: boolean;
	readablePrivateDomains: string[];
}

export interface MemoryBackendHealth {
	name: string;
	status: 'healthy' | 'unhealthy' | string;
	detail: string | null;
	consecutiveFailures?: number;
}

export interface MemoryBackendConfig {
	name: string;
	enabled: boolean;
	weight: number;
	settings: Record<string, unknown>;
}

export interface MemoryBackendsStatus {
	primary: MemoryBackendHealth;
	overlays: MemoryBackendHealth[];
	configuredOverlays: MemoryBackendConfig[];
}

interface ApiMemoryAgentInfo {
	id: string;
	label: string;
	memory_domain: string;
	can_write: boolean;
	can_read_shared: boolean;
	readable_private_domains: string[];
}

interface ApiMemoryBackendHealth {
	name: string;
	status: 'healthy' | 'unhealthy' | string;
	detail?: string | null;
	consecutive_failures?: number;
}

interface ApiMemoryBackendConfig {
	name: string;
	enabled: boolean;
	weight: number;
	settings?: Record<string, unknown>;
}

interface ApiMemoryBackendsStatus {
	primary: ApiMemoryBackendHealth;
	overlays: ApiMemoryBackendHealth[];
	configured_overlays: ApiMemoryBackendConfig[];
}

export interface MemoryRecord {
	id: string;
	content: string;
	domain: string;
	visibility: 'private' | 'shared';
	importance: number;
	tags: string[];
	source: string;
	createdAt: Date;
	updatedAt?: Date | null;
	deletedAt?: Date | null;
	score: number;
	metadata: Record<string, unknown>;
}

interface ApiMemoryRecord {
	id: string;
	content: string;
	domain: string;
	visibility: 'private' | 'shared';
	importance: number;
	tags: string[];
	source: string;
	created_at: string;
	updated_at?: string | null;
	deleted_at?: string | null;
	score?: number;
	metadata?: Record<string, unknown>;
}

interface CreateMemoryRecordPayload {
	agent: string;
	content: string;
	visibility: 'private' | 'shared';
	importance: number;
	tags: string[];
	domain?: string;
	metadata?: Record<string, unknown>;
}

interface UpdateMemoryRecordPayload {
	agent: string;
	content?: string;
	visibility?: 'private' | 'shared';
	importance?: number;
	tags?: string[];
	metadata?: Record<string, unknown>;
}

async function fetchJson<T>(url: string, errorPrefix: string, init?: RequestInit): Promise<T> {
	const response = await fetch(url, init);
	if (!response.ok) {
		throw new ApiError(`${errorPrefix} (${response.status})`, response.status);
	}
	return (await response.json()) as T;
}

function toMemoryAgent(raw: ApiMemoryAgentInfo): MemoryAgentInfo {
	return {
		id: raw.id,
		label: raw.label,
		memoryDomain: raw.memory_domain,
		canWrite: raw.can_write,
		canReadShared: raw.can_read_shared,
		readablePrivateDomains: raw.readable_private_domains ?? []
	};
}

function toMemoryRecord(raw: ApiMemoryRecord): MemoryRecord {
	return {
		id: raw.id,
		content: raw.content,
		domain: raw.domain,
		visibility: raw.visibility,
		importance: raw.importance,
		tags: raw.tags ?? [],
		source: raw.source,
		createdAt: new Date(raw.created_at),
		updatedAt: raw.updated_at ? new Date(raw.updated_at) : null,
		deletedAt: raw.deleted_at ? new Date(raw.deleted_at) : null,
		score: raw.score ?? 0,
		metadata: raw.metadata ?? {}
	};
}

function toMemoryBackendHealth(raw: ApiMemoryBackendHealth): MemoryBackendHealth {
	return {
		name: raw.name,
		status: raw.status,
		detail: raw.detail ?? null,
		consecutiveFailures:
			typeof raw.consecutive_failures === 'number' ? raw.consecutive_failures : undefined
	};
}

function toMemoryBackendConfig(raw: ApiMemoryBackendConfig): MemoryBackendConfig {
	return {
		name: raw.name,
		enabled: raw.enabled,
		weight: raw.weight,
		settings: raw.settings ?? {}
	};
}

export async function listMemoryAgents(): Promise<MemoryAgentInfo[]> {
	const body = await fetchJson<ApiMemoryAgentInfo[]>(
		'/api/memory/agents',
		'Failed to load memory agents'
	);
	return body.map(toMemoryAgent);
}

export async function listMemoryBackends(): Promise<MemoryBackendsStatus> {
	const body = await fetchJson<ApiMemoryBackendsStatus>(
		'/api/memory/backends',
		'Failed to load memory backends'
	);
	return {
		primary: toMemoryBackendHealth(body.primary),
		overlays: (body.overlays ?? []).map(toMemoryBackendHealth),
		configuredOverlays: (body.configured_overlays ?? []).map(toMemoryBackendConfig)
	};
}

export async function listMemoryRecords(
	agent: string,
	options?: { domain?: string; limit?: number; offset?: number }
): Promise<MemoryRecord[]> {
	const qs = new URLSearchParams();
	qs.set('agent', agent);
	if (options?.domain) qs.set('domain', options.domain);
	if (options?.limit !== undefined) qs.set('limit', String(options.limit));
	if (options?.offset !== undefined) qs.set('offset', String(options.offset));
	const body = await fetchJson<ApiMemoryRecord[]>(
		`/api/memory/records?${qs.toString()}`,
		'Failed to load memory records'
	);
	return body.map(toMemoryRecord);
}

export async function searchMemoryRecords(
	agent: string,
	query: string,
	options?: { domain?: string; limit?: number }
): Promise<MemoryRecord[]> {
	const qs = new URLSearchParams();
	qs.set('agent', agent);
	qs.set('q', query);
	if (options?.domain) qs.set('domain', options.domain);
	if (options?.limit !== undefined) qs.set('limit', String(options.limit));
	const body = await fetchJson<ApiMemoryRecord[]>(
		`/api/memory/records/search?${qs.toString()}`,
		'Failed to search memory records'
	);
	return body.map(toMemoryRecord);
}

export async function createMemoryRecord(payload: CreateMemoryRecordPayload): Promise<MemoryRecord> {
	const body = await fetchJson<ApiMemoryRecord>('/api/memory/records', 'Failed to create memory record', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(payload)
	});
	return toMemoryRecord(body);
}

export async function updateMemoryRecord(
	recordId: string,
	payload: UpdateMemoryRecordPayload
): Promise<MemoryRecord> {
	const body = await fetchJson<ApiMemoryRecord>(
		`/api/memory/records/${encodeURIComponent(recordId)}`,
		'Failed to update memory record',
		{
			method: 'PATCH',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify(payload)
		}
	);
	return toMemoryRecord(body);
}

export async function forgetMemoryRecord(agent: string, recordId: string): Promise<void> {
	const response = await fetch(`/api/memory/records/${recordId}?agent=${encodeURIComponent(agent)}`, {
		method: 'DELETE'
	});
	if (!response.ok) {
		throw new ApiError(`Failed to forget memory record (${response.status})`, response.status);
	}
}
