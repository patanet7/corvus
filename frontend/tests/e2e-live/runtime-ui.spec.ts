import { expect, test } from '@playwright/test';
import {
	apiListAgents,
	sendComposerMessage,
	startFreshChat,
	waitForAssistantToSettle,
	waitForAssistantMessageInSession,
	waitForSessionByUserMarker
} from './helpers';

test.describe('Live Runtime UI', () => {
	test('renders expandable runtime timeline in transcript', async ({ page, request }) => {
		const marker = `PW_RUNTIME_TIMELINE_${Date.now()}`;
		await page.goto('/');
		await startFreshChat(page);

		await sendComposerMessage(page, `Reply with exact token ${marker} and one short sentence.`);
		const located = await waitForSessionByUserMarker(request, marker, 120_000);
		expect(located).not.toBeNull();
		if (!located) return;

		await waitForAssistantMessageInSession(request, located.sessionId, 120_000);
		await waitForAssistantToSettle(page, 120_000);
		await expect(page.getByText(marker, { exact: false }).first()).toBeVisible({ timeout: 30_000 });

		const transcriptRow = page.locator('div.flex-1.min-w-0').filter({
			has: page.getByText(marker, { exact: false })
		});
		const timelineToggle = transcriptRow
			.locator('button[aria-label="Toggle assistant runtime details"]')
			.last();
		await expect(timelineToggle).toBeVisible({ timeout: 30_000 });
		await expect(timelineToggle).toHaveAttribute('aria-expanded', 'false');

		const timelineStack = page.locator('.runtime-stack').last();
		await expect(timelineStack).toContainText(/thinking|phase|result|tool|todo/i);
	});

	test('mobile viewport keeps overlays and controls usable', async ({ page, request }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto('/');
		await startFreshChat(page);

		const agents = await apiListAgents(request);
		test.skip(agents.length === 0, 'No agents returned by /api/agents');
		const mentionAgent = (agents.find((agent) => agent.id !== 'general') ?? agents[0]).id;

		const composer = page.getByPlaceholder('Message Corvus...').first();
		await expect(composer).toBeVisible();

		await composer.fill('/');
		const slashOption = page.getByRole('button', { name: '/new' }).first();
		await expect(slashOption).toBeVisible({ timeout: 10_000 });

		const slashBox = await slashOption.boundingBox();
		const composerBox = await composer.boundingBox();
		expect(slashBox).not.toBeNull();
		expect(composerBox).not.toBeNull();
		if (slashBox && composerBox) {
			expect(slashBox.y + slashBox.height).toBeLessThanOrEqual(composerBox.y + 4);
		}

		await composer.fill(`@${mentionAgent.slice(0, 2)}`);
		const mentionOption = page.getByRole('button', { name: `@${mentionAgent}` }).first();
		await expect(mentionOption).toBeVisible({ timeout: 10_000 });

		const mentionBox = await mentionOption.boundingBox();
		const composerBox2 = await composer.boundingBox();
		expect(mentionBox).not.toBeNull();
		expect(composerBox2).not.toBeNull();
		if (mentionBox && composerBox2) {
			expect(mentionBox.y + mentionBox.height).toBeLessThanOrEqual(composerBox2.y + 4);
		}

		await composer.fill('');
		const modelTrigger = page.locator('button[aria-haspopup="listbox"]').first();
		await expect(modelTrigger).toBeVisible();
		await modelTrigger.click();
		const modelList = page.getByRole('listbox', { name: 'Select model' });
		await expect(modelList).toBeVisible();

		const modelListBox = await modelList.boundingBox();
		const modelTriggerBox = await modelTrigger.boundingBox();
		expect(modelListBox).not.toBeNull();
		expect(modelTriggerBox).not.toBeNull();
		if (modelListBox && modelTriggerBox) {
			expect(Math.abs(modelListBox.x - modelTriggerBox.x)).toBeLessThanOrEqual(24);
		}

		await page.getByRole('button', { name: 'Close model selector' }).click();

		await sendComposerMessage(
			page,
			`Write numbers 1-180 as a comma-separated sequence. Token: PW_MOBILE_STREAM_${Date.now()}`
		);

		const stopButton = page.getByRole('button', { name: 'Stop generation' });
		await expect(stopButton).toBeVisible({ timeout: 45_000 });
		await stopButton.click();
		await waitForAssistantToSettle(page, 60_000);
		await expect(composer).toBeVisible();

		const sessionSidebar = page.locator('aside[aria-label="Session sidebar"]');
		if ((await sessionSidebar.count()) > 0) {
			await expect(sessionSidebar).toBeVisible();
		}
		await page
			.getByRole('navigation', { name: 'Mode navigation' })
			.getByRole('button', { name: 'Tasks', exact: true })
			.click();
		const taskSidebar = page.locator('aside[aria-label="Task sidebar"]');
		if ((await taskSidebar.count()) > 0) {
			await expect(taskSidebar).toBeVisible();
		} else {
			await expect(
				page.getByRole('navigation', { name: 'Mode navigation' })
			).toBeVisible();
		}
	});
});
