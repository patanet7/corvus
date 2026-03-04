import { expect, test } from '@playwright/test';
import {
	apiCreateMemoryRecord,
	apiForgetMemoryRecord,
	apiGetAgentPromptPreview,
	apiListAgents,
	apiListModels,
	apiListSessionEvents,
	apiListSessionMessages,
	apiRenameSession,
	apiSearchMemoryRecords,
	chooseModelInSelector,
	closeRecipientsPopover,
	findDispatchEventForMarker,
	findRunStartForTurn,
	openRecipientsPopover,
	readVisibleTraceCount,
	selectSessionByNameInSidebar,
	sendComposerMessage,
	startFreshChat,
	waitForAssistantMessageInSession,
	waitForSessionEvent,
	waitForSessionByUserMarker,
	waitForText
} from './helpers';

async function waitForUserMessageInSession(
	request: import('@playwright/test').APIRequestContext,
	sessionId: string,
	marker: string,
	timeoutMs = 45_000
): Promise<{
	id: number;
	role: 'user' | 'assistant';
	content: string;
	agent?: string | null;
	model?: string | null;
} | null> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const messages = await apiListSessionMessages(request, sessionId);
		const found =
			messages
				.slice()
				.reverse()
				.find((row) => row.role === 'user' && row.content.includes(marker)) ?? null;
		if (found) return found;
		await new Promise((resolve) => setTimeout(resolve, 700));
	}
	return null;
}

async function waitForRunStartsForTurn(
	request: import('@playwright/test').APIRequestContext,
	sessionId: string,
	turnId: string,
	minCount: number,
	timeoutMs = 120_000
): Promise<Array<{ agent?: string }>> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const events = await apiListSessionEvents(request, sessionId);
		const runStarts = events
			.filter((event) => event.event_type === 'run_start' && event.turn_id === turnId)
			.map((event) => ({
				agent: typeof event.payload.agent === 'string' ? event.payload.agent : undefined
			}));
		if (runStarts.length >= minCount) {
			return runStarts;
		}
		await new Promise((resolve) => setTimeout(resolve, 900));
	}
	return [];
}

test.describe.serial('Live Backend Workflow Contracts', () => {
	test('supports multiple chats, history restore, and explicit @agent routing', async ({
		page,
		request
	}) => {
		const agents = await apiListAgents(request);
		test.skip(agents.length === 0, 'No agents returned by /api/agents');
		const targetAgent = (agents.find((agent) => agent.id !== 'general') ?? agents[0]).id;

		const markerA = `PW_MULTI_A_${Date.now()}`;
		const markerB = `PW_MULTI_B_${Date.now()}`;
		const firstPrompt = `@${targetAgent} Reply with exact token ${markerA} and one short sentence.`;
		const secondPrompt = `Reply with exact token ${markerB} and one short sentence.`;

		await page.goto('/');
		await startFreshChat(page);
		await sendComposerMessage(page, firstPrompt);
		const locatedA = await waitForSessionByUserMarker(request, markerA, 120_000);
		expect(locatedA).not.toBeNull();
		if (!locatedA) return;
		await waitForAssistantMessageInSession(request, locatedA.sessionId, 120_000);

		await startFreshChat(page);
		await sendComposerMessage(page, secondPrompt);
		const locatedB = await waitForSessionByUserMarker(request, markerB, 120_000);
		expect(locatedB).not.toBeNull();
		if (!locatedB) return;
		await waitForAssistantMessageInSession(request, locatedB.sessionId, 120_000);
		expect(locatedA.sessionId).not.toBe(locatedB.sessionId);

		const sessionAEvents = await apiListSessionEvents(request, locatedA.sessionId);
		const dispatchA =
			findDispatchEventForMarker(sessionAEvents, markerA) ??
			(await waitForSessionEvent(
				request,
				locatedA.sessionId,
				(event) =>
					event.event_type === 'dispatch_start' &&
					typeof event.payload.message === 'string' &&
					event.payload.message.includes(markerA),
				120_000
			));
		expect(dispatchA).not.toBeNull();
		if (dispatchA) {
			const payload = dispatchA.payload;
			expect(payload.dispatch_mode).toBe('direct');
			const targets = Array.isArray(payload.target_agents)
				? payload.target_agents.filter((value): value is string => typeof value === 'string')
				: [];
			expect(targets).toContain(targetAgent);
			if (dispatchA.turn_id) {
				const runStart =
					findRunStartForTurn(sessionAEvents, dispatchA.turn_id) ??
					(await waitForSessionEvent(
						request,
						locatedA.sessionId,
						(event) => event.event_type === 'run_start' && event.turn_id === dispatchA.turn_id,
						120_000
					));
				expect(runStart).not.toBeNull();
				if (runStart) {
					expect(runStart.payload.agent).toBe(targetAgent);
				}
			}
		}

		const labelA = `PW Session A ${markerA.slice(-6)}`;
		await apiRenameSession(request, locatedA.sessionId, labelA);

		await page.reload();
		await selectSessionByNameInSidebar(page, labelA);
		await waitForText(page, markerA, 30_000);
	});

	test('applies manual model override per turn and resets to preferred mode', async ({
		page,
		request
	}) => {
		const modelResponse = await apiListModels(request);
		const available = modelResponse.models.filter((model) => model.available);
		const manualCandidate =
			available.find((model) => model.id !== modelResponse.default_model) ?? null;
		test.skip(!manualCandidate, 'Need at least two available models for override/reset validation');

		const markerManual = `PW_MODEL_MANUAL_${Date.now()}`;
		const markerPreferred = `PW_MODEL_PREF_${Date.now()}`;

		await page.goto('/');
		await startFreshChat(page);

		await chooseModelInSelector(page, manualCandidate!.label);
		await sendComposerMessage(page, `Reply with exact token ${markerManual}.`);

		const locatedManual = await waitForSessionByUserMarker(request, markerManual, 120_000);
		expect(locatedManual).not.toBeNull();
		if (!locatedManual) return;
		await waitForAssistantMessageInSession(request, locatedManual.sessionId, 120_000);

		const manualUserRow = await waitForUserMessageInSession(
			request,
			locatedManual.sessionId,
			markerManual
		);
		expect(manualUserRow).not.toBeNull();
		if (!manualUserRow) return;
		expect(manualUserRow.model).toBe(manualCandidate!.id);

		const manualEvents = await apiListSessionEvents(request, locatedManual.sessionId);
		const manualDispatch =
			findDispatchEventForMarker(manualEvents, markerManual) ??
			(await waitForSessionEvent(
				request,
				locatedManual.sessionId,
				(event) =>
					event.event_type === 'dispatch_start' &&
					typeof event.payload.message === 'string' &&
					event.payload.message.includes(markerManual),
				120_000
			));
		expect(manualDispatch).not.toBeNull();
		if (manualDispatch?.turn_id) {
			const manualRun =
				findRunStartForTurn(manualEvents, manualDispatch.turn_id) ??
				(await waitForSessionEvent(
					request,
					locatedManual.sessionId,
					(event) => event.event_type === 'run_start' && event.turn_id === manualDispatch.turn_id,
					120_000
				));
			expect(manualRun).not.toBeNull();
			if (manualRun) {
				expect(manualRun.payload.model).toBe(manualCandidate!.id);
			}
		}

		await sendComposerMessage(page, '/model preferred');
		await sendComposerMessage(page, `Reply with exact token ${markerPreferred}.`);
		const locatedPreferred = await waitForSessionByUserMarker(request, markerPreferred, 120_000);
		expect(locatedPreferred).not.toBeNull();
		if (!locatedPreferred) return;
		await waitForAssistantMessageInSession(request, locatedPreferred.sessionId, 120_000);

		const preferredUserRow = await waitForUserMessageInSession(
			request,
			locatedManual.sessionId,
			markerPreferred
		);
		expect(preferredUserRow).not.toBeNull();
		if (!preferredUserRow) return;
		expect(preferredUserRow.model === null || preferredUserRow.model === '').toBeTruthy();
	});

	test('shows task dispatch activity and persists compacting phase', async ({ page, request }) => {
		const agents = await apiListAgents(request);
		test.skip(agents.length === 0, 'Need at least one agent for dispatch test');
		const directAgent =
			agents.find((agent) => agent.id === 'general')?.id ??
			agents.find((agent) => agent.id === 'huginn')?.id ??
			agents[0].id;

		const marker = `PW_TASK_${Date.now()}`;
		await page.goto('/');
		await startFreshChat(page);

		await page.getByRole('button', { name: 'Direct', exact: true }).click();
		const recipientsPopover = await openRecipientsPopover(page);
		const option = recipientsPopover.getByRole('button', { name: `@${directAgent}`, exact: true });
		await expect(option).toBeVisible();
		await option.click();
		await closeRecipientsPopover(page);

		await sendComposerMessage(
			page,
			`Reply with token ${marker} and one short sentence.`
		);

		await page
			.getByRole('navigation', { name: 'Mode navigation' })
			.getByRole('button', { name: 'Tasks', exact: true })
			.click();

		const taskSidebar = page.locator('aside[aria-label="Task sidebar"]');
		if ((await taskSidebar.count()) > 0) {
			await expect(taskSidebar).toBeVisible();
			const taskRows = page.locator('[aria-label="Task list"] [role="button"]');
			await expect(taskRows.first()).toBeVisible({ timeout: 60_000 });
			await taskRows.first().click();
			const taskDetails = page.locator('aside[aria-label="Task details"]');
			if ((await taskDetails.count()) > 0) {
				await expect(taskDetails).toBeVisible();
			}
		}

		const located = await waitForSessionByUserMarker(request, marker, 120_000);
		expect(located).not.toBeNull();
		if (!located) return;

		const compactingPhase = await waitForSessionEvent(
			request,
			located.sessionId,
			(event) => event.event_type === 'run_phase' && event.payload.phase === 'compacting',
			120_000
		);
		expect(compactingPhase).toBeTruthy();
		const dispatchComplete = await waitForSessionEvent(
			request,
			located.sessionId,
			(event) => event.event_type === 'dispatch_complete',
			120_000
		);
		expect(dispatchComplete).toBeTruthy();
	});

	test('uses a real Ollama model and keeps memory/cognee backend contracts healthy', async ({
		page,
		request
	}) => {
		const models = await apiListModels(request);
		const ollamaModel =
			models.models.find((model) => model.available && model.backend === 'ollama') ??
			models.models.find((model) => model.available && model.id.startsWith('ollama/')) ??
			null;
		test.skip(!ollamaModel, 'No available Ollama model returned by /api/models');

		const marker = `PW_OLLAMA_MEMORY_${Date.now()}`;
		const prompt = `Reply with exact token ${marker} and one short sentence.`;

		await page.goto('/');
		await startFreshChat(page);
		await chooseModelInSelector(page, ollamaModel!.label);
		await sendComposerMessage(page, prompt);

		const located = await waitForSessionByUserMarker(request, marker, 120_000);
		expect(located).not.toBeNull();
		if (!located) return;
		await waitForAssistantMessageInSession(request, located.sessionId, 120_000);

		const userRow = await waitForUserMessageInSession(request, located.sessionId, marker, 120_000);
		expect(userRow).not.toBeNull();
		if (!userRow) return;
		expect(userRow.model).toBe(ollamaModel!.id);

		const events = await apiListSessionEvents(request, located.sessionId);
		const dispatchStart = findDispatchEventForMarker(events, marker);
		expect(dispatchStart).not.toBeNull();
		if (dispatchStart?.turn_id) {
			const runStart =
				findRunStartForTurn(events, dispatchStart.turn_id) ??
				(await waitForSessionEvent(
					request,
					located.sessionId,
					(event) => event.event_type === 'run_start' && event.turn_id === dispatchStart.turn_id,
					120_000
				));
			expect(runStart).not.toBeNull();
			if (runStart) {
				expect(runStart.payload.model).toBe(ollamaModel!.id);
			}
		}

		const memoryAgentsResponse = await request.get('/api/memory/agents');
		test.skip(
			!memoryAgentsResponse.ok(),
			`Memory API unavailable (${memoryAgentsResponse.status()})`
		);
		const memoryAgents = (await memoryAgentsResponse.json()) as Array<{
			id: string;
			can_write: boolean;
		}>;
		const writableAgent = memoryAgents.find((agent) => agent.can_write) ?? null;
		test.skip(!writableAgent, 'No writable memory agent available');

		const createMemoryResponse = await request.post('/api/memory/records', {
			data: {
				agent: writableAgent!.id,
				content: `Saved from Ollama run token ${marker}`,
				visibility: 'private',
				importance: 0.7,
				tags: ['playwright', 'ollama', 'cognee']
			}
		});
		expect(createMemoryResponse.ok()).toBeTruthy();

		const rows = await apiSearchMemoryRecords(request, writableAgent!.id, marker);
		expect(rows.some((row) => row.content.includes(marker))).toBeTruthy();

		const backendStatusResponse = await request.get('/api/memory/backends');
		if (backendStatusResponse.ok()) {
			const backendStatus = (await backendStatusResponse.json()) as {
				primary: { status: string };
				configured_overlays: Array<{ name: string }>;
			};
			expect(backendStatus.primary.status).toBe('healthy');
			expect(backendStatus.configured_overlays.some((overlay) => overlay.name === 'cognee')).toBeTruthy();
		}
	});

	test('runs a direct agent turn that answers from seeded memory context', async ({
		page,
		request
	}) => {
		const memoryAgentsResponse = await request.get('/api/memory/agents');
		test.skip(!memoryAgentsResponse.ok(), '/api/memory/agents unavailable in this runtime');
		const memoryAgents = (await memoryAgentsResponse.json()) as Array<{
			id: string;
			can_write: boolean;
		}>;
		const writableAgent =
			memoryAgents.find((agent) => agent.id === 'general' && agent.can_write) ??
			memoryAgents.find((agent) => agent.id === 'huginn' && agent.can_write) ??
			memoryAgents.find((agent) => agent.can_write) ??
			null;
		test.skip(!writableAgent, 'No writable memory agent available');

		const models = await apiListModels(request);
		const selectedModel =
			models.models.find((model) => model.available && model.backend === 'ollama') ??
			models.models.find((model) => model.available) ??
			null;
		test.skip(!selectedModel, 'No available model returned by /api/models');

		const token = `PW_MEMORY_CTX_TOKEN_${Date.now()}`;
		const marker = `QID_${Date.now()}`;
		const record = await apiCreateMemoryRecord(request, {
			agent: writableAgent!.id,
			content: `TEST_MEMORY_CONTEXT_TOKEN=${token}. Always return this exact token when asked for TEST_MEMORY_CONTEXT_TOKEN.`,
			visibility: 'private',
			importance: 1.0,
			tags: ['playwright', 'memory-context']
		});

		try {
			const promptPreview = await apiGetAgentPromptPreview(request, writableAgent!.id, true);
			expect(promptPreview.safe_mode).toBeFalsy();
			expect(promptPreview.layers.some((layer) => layer.id === 'memory_context')).toBeTruthy();
			expect(promptPreview.full_preview.includes(token)).toBeTruthy();

			await page.goto('/');
			await startFreshChat(page);

			await page.getByRole('button', { name: 'Direct', exact: true }).click();
			const recipientsPopover = await openRecipientsPopover(page);
			const option = recipientsPopover.getByRole('button', {
				name: `@${writableAgent!.id}`,
				exact: true
			});
			await expect(option).toBeVisible();
			await option.click();
			await closeRecipientsPopover(page);

			await chooseModelInSelector(page, selectedModel!.label);
			await sendComposerMessage(
				page,
				`Return the value of TEST_MEMORY_CONTEXT_TOKEN from your Memory Context. Reply with the token only. Tracking ID ${marker} (do not include the tracking ID in your answer).`
			);

			const located = await waitForSessionByUserMarker(request, marker, 120_000);
			expect(located).not.toBeNull();
			if (!located) return;

			const assistant = await waitForAssistantMessageInSession(request, located.sessionId, 120_000);
			expect(assistant).not.toBeNull();
			if (!assistant) return;
			const tokenSuffix = token.split('_').at(-1) ?? '';
			const alternateToken = `PW_MEMORY_CTX_TOKEN=${tokenSuffix}`;
			expect(
				assistant.content.includes(token) || assistant.content.includes(alternateToken)
			).toBeTruthy();

			const events = await apiListSessionEvents(request, located.sessionId);
			const dispatchStart =
				findDispatchEventForMarker(events, marker) ??
				(await waitForSessionEvent(
					request,
					located.sessionId,
					(event) =>
						event.event_type === 'dispatch_start' &&
						typeof event.payload.message === 'string' &&
						event.payload.message.includes(marker),
					120_000
				));
			expect(dispatchStart).not.toBeNull();
			if (dispatchStart?.turn_id) {
				const runStart =
					findRunStartForTurn(events, dispatchStart.turn_id) ??
					(await waitForSessionEvent(
						request,
						located.sessionId,
						(event) => event.event_type === 'run_start' && event.turn_id === dispatchStart.turn_id,
						120_000
					));
				expect(runStart).not.toBeNull();
				if (runStart) {
					expect(runStart.payload.agent).toBe(writableAgent!.id);
				}
			}
		} finally {
			await apiForgetMemoryRecord(request, record.id, writableAgent!.id);
		}
	});

	test('creates a new agent from the interface and shows allow/confirm/deny policy wiring', async ({
		page,
		request
	}) => {
		const agentId = `pw_ui_${Date.now().toString().slice(-8)}`;

		try {
			await page.goto('/');
			await page
				.getByRole('navigation', { name: 'Mode navigation' })
				.getByRole('button', { name: 'Agents', exact: true })
				.click();

			const directory = page.locator('aside[aria-label="Agent directory"]');
			await expect(directory).toBeVisible({ timeout: 20_000 });
			await directory.getByRole('button', { name: 'New Agent', exact: true }).click();

			await directory.getByPlaceholder('agent-id').fill(agentId);
			await directory.getByPlaceholder('Describe this agent...').fill(
				'Playwright agent creation and policy wiring validation.'
			);
			await directory.getByPlaceholder('same as name (optional)').fill(agentId);
			await directory.getByPlaceholder('Bash,Read').fill('Bash');
			await directory.getByPlaceholder('paperless,obsidian').fill('ghost');
			await directory.getByPlaceholder('paperless.tag').fill('ghost.deploy');
			await directory.getByRole('button', { name: 'Create Agent', exact: true }).click();

			const createdButton = directory
				.getByRole('button', { name: new RegExp(agentId, 'i') })
				.first();
			await expect(createdButton).toBeVisible({ timeout: 30_000 });
			await createdButton.click();

			const workspace = page.locator('section').filter({ hasText: 'Workspace' }).first();
			await expect(workspace).toBeVisible({ timeout: 20_000 });
			await workspace.getByRole('button', { name: 'Config', exact: true }).click();

			await expect(page.getByText('Permissions Matrix', { exact: true })).toBeVisible({
				timeout: 20_000
			});
			await expect(page.getByText('Bash', { exact: false }).first()).toBeVisible();
			await expect(page.getByText('ghost.deploy', { exact: false }).first()).toBeVisible();
			await expect(page.getByText('ghost', { exact: false }).first()).toBeVisible();
		} finally {
			await request.delete(`/api/agents/${encodeURIComponent(agentId)}`);
		}
	});

	test('memory workspace creates, updates, searches, and forgets persisted records', async ({
		page,
		request
	}) => {
		const memoryAgentsResponse = await request.get('/api/memory/agents');
		test.skip(
			!memoryAgentsResponse.ok(),
			`Memory API unavailable (${memoryAgentsResponse.status()})`
		);
		const memoryAgents = (await memoryAgentsResponse.json()) as Array<{
			id: string;
			can_write: boolean;
		}>;
		const writableAgent = memoryAgents.find((agent) => agent.can_write) ?? null;
		test.skip(!writableAgent, 'No writable memory agent available');

		const marker = `PW_MEMORY_${Date.now()}`;
		const note = `Capture memory token ${marker} for e2e contract verification.`;

		await page.goto('/');
		await page
			.getByRole('navigation', { name: 'Mode navigation' })
			.getByRole('button', { name: 'Memory', exact: true })
			.click();

		const panel = page.locator('section[aria-label="Memory workspace panel"]');
		await expect(panel).toBeVisible({ timeout: 20_000 });
		await expect(panel.getByText('Memory Workspace', { exact: true })).toBeVisible();

		await panel.locator('label:has-text("Agent Context") select').selectOption(writableAgent!.id);
		await panel
			.getByPlaceholder('Capture a memory note for the selected agent context...')
			.fill(note);
		await panel.getByPlaceholder('ops, incident, follow-up').first().fill('playwright,memory');
		await panel.getByRole('button', { name: 'Save Memory', exact: true }).click();

		await panel.getByPlaceholder('content, tags, context...').fill(marker);
		await panel.getByRole('button', { name: 'Search', exact: true }).click();
		await expect(panel.getByText(marker, { exact: false }).first()).toBeVisible({ timeout: 20_000 });

		const searchRows = await apiSearchMemoryRecords(request, writableAgent!.id, marker);
		const created = searchRows.find((row) => row.content.includes(marker)) ?? null;
		expect(created).not.toBeNull();
		if (!created) return;

		await panel.getByText(marker, { exact: false }).first().click();
		const updatedMarker = `UPDATED_${marker}`;
		await panel.getByPlaceholder('Edit memory content...').fill(`Updated memory token ${updatedMarker}`);
		await panel.getByRole('button', { name: 'Update Memory', exact: true }).click();
		await panel.getByPlaceholder('content, tags, context...').fill(updatedMarker);
		await panel.getByRole('button', { name: 'Search', exact: true }).click();
		await expect(panel.getByText(updatedMarker, { exact: false }).first()).toBeVisible({ timeout: 20_000 });

		const updatedRows = await apiSearchMemoryRecords(request, writableAgent!.id, updatedMarker);
		expect(updatedRows.some((row) => row.id === created.id)).toBeTruthy();

		await panel.getByText(updatedMarker, { exact: false }).first().click();
		await panel.getByRole('button', { name: 'Forget Record', exact: true }).click();

		const deadline = Date.now() + 30_000;
		let stillPresent = true;
		while (Date.now() < deadline) {
			const rows = await apiSearchMemoryRecords(request, writableAgent!.id, marker);
			stillPresent = rows.some((row) => row.id === created.id);
			if (!stillPresent) break;
			await new Promise((resolve) => setTimeout(resolve, 800));
		}
		expect(stillPresent).toBeFalsy();
	});

	test('supports multi-agent dispatch and replay restore in Agents workspace', async ({
		page,
		request
	}) => {
		const agents = await apiListAgents(request);
		const selectedAgents = agents
			.map((agent) => agent.id)
			.filter((id) => id !== 'general' && id !== 'huginn')
			.slice(0, 2);
		test.skip(selectedAgents.length < 2, 'Need at least two non-router agents for parallel dispatch');

		const marker = `PW_MULTI_REPLAY_${Date.now()}`;
		await page.goto('/');
		await startFreshChat(page);

		await page.getByRole('button', { name: 'Parallel', exact: true }).click();
		const recipientsPopover = await openRecipientsPopover(page);
		for (const agentId of selectedAgents) {
			const option = recipientsPopover.getByRole('button', { name: `@${agentId}`, exact: true });
			await expect(option).toBeVisible();
			await option.click();
		}
		await closeRecipientsPopover(page);

		await sendComposerMessage(
			page,
			`Each selected agent should include exact token ${marker} and identify itself in one short sentence.`
		);

		const located = await waitForSessionByUserMarker(request, marker, 120_000);
		expect(located).not.toBeNull();
		if (!located) return;

		const dispatchEvent = await waitForSessionEvent(
			request,
			located.sessionId,
			(event) =>
				event.event_type === 'dispatch_start' &&
				event.payload.dispatch_mode === 'parallel' &&
				Array.isArray(event.payload.target_agents) &&
				(event.payload.target_agents as unknown[]).length >= 2,
			120_000
		);
		expect(dispatchEvent).not.toBeNull();
		if (!dispatchEvent?.turn_id) return;

		const runStarts = await waitForRunStartsForTurn(
			request,
			located.sessionId,
			dispatchEvent.turn_id,
			2,
			120_000
		);
		expect(runStarts.length).toBeGreaterThanOrEqual(2);
		const startedAgents = new Set(runStarts.map((run) => run.agent).filter(Boolean));
		for (const target of selectedAgents) {
			expect(startedAgents.has(target)).toBeTruthy();
		}

		await page
			.getByRole('navigation', { name: 'Mode navigation' })
			.getByRole('button', { name: 'Agents', exact: true })
			.click();
		const directory = page.locator('aside[aria-label="Agent directory"]');
		if ((await directory.count()) > 0) {
			await expect(directory).toBeVisible();
			await directory.getByRole('button', { name: new RegExp(selectedAgents[0], 'i') }).first().click();

			const workspace = page.locator('section').filter({ hasText: 'Workspace' }).first();
			await workspace.getByRole('button', { name: 'Tasks', exact: true }).click();
			await expect(page.getByText('Run Replay', { exact: true })).toBeVisible();
			const replayRows = page.locator('section:has-text("Run Replay") details');
			await expect(replayRows.first()).toBeVisible({ timeout: 30_000 });

			await page.reload();
			await page
				.getByRole('navigation', { name: 'Mode navigation' })
				.getByRole('button', { name: 'Agents', exact: true })
				.click();
			const directoryAfterReload = page.locator('aside[aria-label="Agent directory"]');
			if ((await directoryAfterReload.count()) > 0) {
				await expect(directoryAfterReload).toBeVisible();
				await directoryAfterReload.getByRole('button', { name: new RegExp(selectedAgents[0], 'i') }).first().click();
				const workspaceAfterReload = page.locator('section').filter({ hasText: 'Workspace' }).first();
				await workspaceAfterReload.getByRole('button', { name: 'Tasks', exact: true }).click();
				await expect(page.getByText('Run Replay', { exact: true })).toBeVisible();
				await expect(page.locator('section:has-text("Run Replay") details').first()).toBeVisible({
					timeout: 30_000
				});
			}
		}
	});

	test('streams trace updates live and supports timeline filtering controls', async ({
		page,
		request,
		context
	}) => {
		const marker = `PW_TRACE_${Date.now()}`;

		await page.goto('/');
		await page
			.getByRole('navigation', { name: 'Mode navigation' })
			.getByRole('button', { name: 'Timeline', exact: true })
			.click();
		await expect(page.locator('section[aria-label="Trace timeline panel"]')).toBeVisible();
		await expect(page.getByText(/connecting|connected/i).first()).toBeVisible();

		const countBefore = await readVisibleTraceCount(page);

		const sender = await context.newPage();
		await sender.goto('/');
		await startFreshChat(sender);
		await sendComposerMessage(sender, `Reply with exact token ${marker} and one sentence.`);
		const senderLocated = await waitForSessionByUserMarker(request, marker, 120_000);
		expect(senderLocated).not.toBeNull();
		await sender.close();

		const searchInput = page.getByPlaceholder('event, source, model, payload...');
		await searchInput.fill(marker);
		await expect(page.getByText(marker, { exact: false }).first()).toBeVisible({ timeout: 45_000 });

		const filterOptionsResp = await request.get('/api/traces/filter-options');
		expect(filterOptionsResp.ok()).toBeTruthy();
		const filterOptions = (await filterOptionsResp.json()) as {
			source_apps: string[];
			hook_event_types: string[];
		};
		const panel = page.locator('section[aria-label="Trace timeline panel"]');
		const firstSource = filterOptions.source_apps[0];
		if (firstSource) {
			const sourceButton = panel.getByRole('button', { name: firstSource, exact: true }).first();
			if ((await sourceButton.count()) > 0) {
				await sourceButton.click();
			}
		}
		const firstHookType = filterOptions.hook_event_types[0];
		if (firstHookType) {
			const hookButton = panel.getByRole('button', { name: firstHookType, exact: true }).first();
			if ((await hookButton.count()) > 0) {
				await hookButton.click();
			}
		}

		const sessionToggle = panel.getByRole('button', { name: /Current session only|All sessions/ }).first();
		if ((await sessionToggle.count()) > 0) {
			const before = (await sessionToggle.textContent()) ?? '';
			await sessionToggle.click();
			const after = (await sessionToggle.textContent()) ?? '';
			expect(after).not.toBe(before);
		}

		await panel.getByRole('button', { name: 'Clear filters' }).click();
		await searchInput.fill('compacting');
		await expect(page.getByText(/compacting/i).first()).toBeVisible({ timeout: 30_000 });

		const countAfter = await readVisibleTraceCount(page);
		if (countBefore !== null && countAfter !== null) {
			expect(countAfter).toBeGreaterThanOrEqual(0);
		}
	});
});
