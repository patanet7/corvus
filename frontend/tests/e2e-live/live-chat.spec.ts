import { expect, test } from '@playwright/test';
import {
	apiListSessionMessages,
	startFreshChat,
	sendComposerMessage,
	waitForAssistantToSettle,
	waitForAssistantMessageInSession,
	waitForSessionByUserMarker,
	waitForText
} from './helpers';

test.describe('Live Backend Chat', () => {
	test('streams live response, settles composer, and resumes session history', async ({
		page,
		request
	}) => {
		const marker = `PW_LIVE_${Date.now()}`;
		const prompt = `Reply with token ${marker} and one short sentence.`;

		await page.goto('/');
		await startFreshChat(page);

		await sendComposerMessage(page, prompt);
		await waitForText(page, prompt, 20_000);
		await waitForAssistantToSettle(page, 40_000);

		const located = await waitForSessionByUserMarker(request, marker);
		expect(located).not.toBeNull();
		if (!located) return;

		const assistantPersisted = await waitForAssistantMessageInSession(request, located.sessionId, 90_000);
		expect(assistantPersisted).not.toBeNull();

		const history = await apiListSessionMessages(request, located.sessionId);
		expect(history.some((row) => row.role === 'user' && (row.content ?? '').includes(marker))).toBeTruthy();
		expect(history.some((row) => row.role === 'assistant' && (row.content ?? '').trim().length > 0)).toBeTruthy();

		await expect(page.locator('[aria-label="Session list"]').getByText(/msgs/).first()).toBeVisible();
	});
});
