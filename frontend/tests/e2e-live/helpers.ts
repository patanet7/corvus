import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

export interface ApiSession {
	id: string;
}

export interface ApiSessionMessage {
	id: number;
	role: 'user' | 'assistant';
	content: string;
	agent?: string | null;
	model?: string | null;
}

export interface ApiSessionEvent {
	id: number;
	session_id: string;
	turn_id?: string | null;
	event_type: string;
	payload: Record<string, unknown>;
}

export interface ApiModelInfo {
	id: string;
	label: string;
	available: boolean;
	backend?: string;
}

export interface ApiModelListResponse {
	models: ApiModelInfo[];
	default_model: string;
}

export interface ApiAgentInfo {
	id: string;
	label: string;
}

export interface ApiMemoryAgentInfo {
	id: string;
	label: string;
	memory_domain: string;
	can_write: boolean;
	can_read_shared: boolean;
	readable_private_domains: string[];
}

export interface ApiMemoryRecord {
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

export interface ApiPromptPreviewLayer {
	id: string;
	title: string;
	source: string;
	char_count: number;
	clipped: boolean;
	content_preview: string;
}

export interface ApiPromptPreview {
	agent: string;
	safe_mode: boolean;
	total_layers: number;
	total_chars: number;
	full_preview: string;
	full_preview_clipped: boolean;
	layers: ApiPromptPreviewLayer[];
}

export interface ApiMemoryBackendHealth {
	name: string;
	status: string;
	detail?: string | null;
	consecutive_failures?: number;
}

export interface ApiMemoryBackendConfig {
	name: string;
	enabled: boolean;
	weight: number;
	settings?: Record<string, unknown>;
}

export interface ApiMemoryBackendsStatus {
	primary: ApiMemoryBackendHealth;
	overlays: ApiMemoryBackendHealth[];
	configured_overlays: ApiMemoryBackendConfig[];
}

export function escapeRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export async function stopIfStreaming(page: Page): Promise<void> {
	const stopButton = page.getByRole('button', { name: 'Stop generation' });
	if ((await stopButton.count()) > 0) {
		await stopButton.first().click();
		await page.waitForTimeout(500);
	}
}

export async function sendComposerMessage(page: Page, message: string): Promise<void> {
	const input = page.getByPlaceholder('Message Corvus...').first();
	await input.click();
	await input.fill('');
	await input.pressSequentially(message, { delay: 4 });
	await expect(input).toHaveValue(message);
	await input.press('Enter');
}

export async function startFreshChat(page: Page): Promise<void> {
	await stopIfStreaming(page);
	await page.getByText('+ New').first().click();
	await expect(page.getByPlaceholder('Message Corvus...').first()).toBeVisible();
	const welcome = page.getByText('Welcome to Corvus');
	if ((await welcome.count()) > 0) {
		await expect(welcome.first()).toBeVisible();
	}
}

export async function waitForAssistantToSettle(page: Page, timeoutMs = 45_000): Promise<void> {
	const stopButton = page.getByRole('button', { name: 'Stop generation' });
	try {
		await expect(stopButton).toHaveCount(0, { timeout: timeoutMs });
		return;
	} catch {
		// If the runtime is still active after timeout, issue one explicit stop
		// so live tests can continue validating persistence contracts.
		if ((await stopButton.count()) > 0) {
			for (let attempt = 0; attempt < 3; attempt += 1) {
				if ((await stopButton.count()) === 0) break;
				await stopButton.first().click();
				await page.waitForTimeout(500);
			}
		}
	}
}

export async function waitForText(page: Page, text: string, timeoutMs = 45_000): Promise<void> {
	await expect(page.getByText(text, { exact: false }).first()).toBeVisible({ timeout: timeoutMs });
}

export async function apiListSessions(request: APIRequestContext): Promise<ApiSession[]> {
	const response = await request.get('/api/sessions?limit=80');
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiSession[];
}

export async function apiListSessionMessages(
	request: APIRequestContext,
	sessionId: string
): Promise<ApiSessionMessage[]> {
	const response = await request.get(`/api/sessions/${sessionId}/messages?limit=4000`);
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiSessionMessage[];
}

export async function apiListSessionEvents(
	request: APIRequestContext,
	sessionId: string
): Promise<ApiSessionEvent[]> {
	const response = await request.get(`/api/sessions/${sessionId}/events?limit=4000`);
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiSessionEvent[];
}

export async function apiRenameSession(
	request: APIRequestContext,
	sessionId: string,
	name: string
): Promise<void> {
	const response = await request.patch(`/api/sessions/${sessionId}`, {
		data: { name }
	});
	expect(response.ok()).toBeTruthy();
}

export async function apiListModels(request: APIRequestContext): Promise<ApiModelListResponse> {
	const response = await request.get('/api/models');
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiModelListResponse;
}

export async function apiListAgents(request: APIRequestContext): Promise<ApiAgentInfo[]> {
	const response = await request.get('/api/agents');
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiAgentInfo[];
}

export async function apiListMemoryAgents(request: APIRequestContext): Promise<ApiMemoryAgentInfo[]> {
	const response = await request.get('/api/memory/agents');
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiMemoryAgentInfo[];
}

export async function apiSearchMemoryRecords(
	request: APIRequestContext,
	agent: string,
	query: string
): Promise<ApiMemoryRecord[]> {
	const response = await request.get(
		`/api/memory/records/search?agent=${encodeURIComponent(agent)}&q=${encodeURIComponent(query)}&limit=80`
	);
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiMemoryRecord[];
}

export async function apiCreateMemoryRecord(
	request: APIRequestContext,
	payload: {
		agent: string;
		content: string;
		visibility?: 'private' | 'shared';
		importance?: number;
		tags?: string[];
		metadata?: Record<string, unknown>;
	}
): Promise<ApiMemoryRecord> {
	const response = await request.post('/api/memory/records', { data: payload });
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiMemoryRecord;
}

export async function apiForgetMemoryRecord(
	request: APIRequestContext,
	recordId: string,
	agent: string
): Promise<void> {
	const response = await request.delete(
		`/api/memory/records/${encodeURIComponent(recordId)}?agent=${encodeURIComponent(agent)}`
	);
	expect(response.ok()).toBeTruthy();
}

export async function apiGetAgentPromptPreview(
	request: APIRequestContext,
	agent: string,
	includeWorkspace = true
): Promise<ApiPromptPreview> {
	const response = await request.get(
		`/api/agents/${encodeURIComponent(agent)}/prompt-preview?include_workspace=${includeWorkspace ? 'true' : 'false'}&max_chars=20000&clip_chars=4000`
	);
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiPromptPreview;
}

export async function apiMemoryBackends(request: APIRequestContext): Promise<ApiMemoryBackendsStatus> {
	const response = await request.get('/api/memory/backends');
	expect(response.ok()).toBeTruthy();
	return (await response.json()) as ApiMemoryBackendsStatus;
}

export async function waitForSessionByUserMarker(
	request: APIRequestContext,
	marker: string,
	timeoutMs = 120_000
): Promise<{ sessionId: string; messages: ApiSessionMessage[] } | null> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const sessions = await apiListSessions(request);
		for (const session of sessions) {
			const messages = await apiListSessionMessages(request, session.id);
			if (messages.some((row) => row.role === 'user' && row.content.includes(marker))) {
				return { sessionId: session.id, messages };
			}
		}
		await new Promise((resolve) => setTimeout(resolve, 900));
	}
	return null;
}

export async function waitForAssistantMessageInSession(
	request: APIRequestContext,
	sessionId: string,
	timeoutMs = 120_000
): Promise<ApiSessionMessage | null> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const messages = await apiListSessionMessages(request, sessionId);
		const assistant =
			messages
				.slice()
				.reverse()
				.find((row) => row.role === 'assistant' && row.content.trim().length > 0) ?? null;
		if (assistant) return assistant;
		await new Promise((resolve) => setTimeout(resolve, 900));
	}
	return null;
}

export async function waitForSessionEvent(
	request: APIRequestContext,
	sessionId: string,
	predicate: (event: ApiSessionEvent) => boolean,
	timeoutMs = 120_000
): Promise<ApiSessionEvent | null> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const events = await apiListSessionEvents(request, sessionId);
		const found = events.find(predicate) ?? null;
		if (found) return found;
		await new Promise((resolve) => setTimeout(resolve, 900));
	}
	return null;
}

export function findDispatchEventForMarker(
	events: ApiSessionEvent[],
	marker: string
): ApiSessionEvent | null {
	for (const event of events) {
		if (event.event_type !== 'dispatch_start') continue;
		const message = event.payload.message;
		if (typeof message === 'string' && message.includes(marker)) {
			return event;
		}
	}
	return null;
}

export function findRunStartForTurn(events: ApiSessionEvent[], turnId: string): ApiSessionEvent | null {
	for (const event of events) {
		if (event.event_type !== 'run_start') continue;
		if ((event.turn_id ?? null) === turnId) return event;
	}
	return null;
}

export async function selectSessionByNameInSidebar(page: Page, sessionName: string): Promise<void> {
	const sidebar = page.locator('aside[aria-label="Session sidebar"]');
	const search = sidebar.getByPlaceholder('Search sessions...');
	await search.fill(sessionName);
	const item = sidebar.getByText(sessionName, { exact: false }).first();
	await expect(item).toBeVisible({ timeout: 20_000 });
	await item.click();
}

export async function chooseModelInSelector(page: Page, optionText: string): Promise<void> {
	const trigger = page.locator('button[aria-haspopup="listbox"]').first();
	await trigger.click();
	const listbox = page.getByRole('listbox', { name: 'Select model' });
	await expect(listbox).toBeVisible({ timeout: 10_000 });
	const option = listbox.getByRole('option', { name: new RegExp(escapeRegExp(optionText), 'i') }).first();
	await expect(option).toBeVisible({ timeout: 10_000 });
	await option.click();
}

export async function readVisibleTraceCount(page: Page): Promise<number | null> {
	const label = page.locator('text=/\\d+ visible event(s)?/');
	if ((await label.count()) === 0) return null;
	const raw = (await label.first().textContent()) ?? '';
	const match = raw.match(/(\d+)\s+visible event/);
	if (!match) return null;
	return Number.parseInt(match[1] ?? '', 10);
}

export async function openRecipientsPopover(page: Page): Promise<Locator> {
	const recipientsButton = page.getByRole('button', { name: 'Recipients' });
	await recipientsButton.click();
	const popover = page.locator('div').filter({ hasText: 'Choose one or more agents.' }).first();
	await expect(popover).toBeVisible({ timeout: 10_000 });
	return popover;
}

export async function closeRecipientsPopover(page: Page): Promise<void> {
	const closeButton = page.getByRole('button', { name: 'Close recipient picker' });
	if ((await closeButton.count()) > 0) {
		await closeButton.first().click();
	}
}
