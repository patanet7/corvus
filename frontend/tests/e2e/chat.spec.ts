import { test, expect, type Page } from '@playwright/test';

function modeButton(page: Page, label: 'Chat' | 'Agents' | 'Tasks' | 'Config' | 'Timeline' | 'Memory') {
	return page
		.getByRole('navigation', { name: 'Mode navigation' })
		.getByRole('button', { name: label, exact: true });
}

test.describe('Chat MVP', () => {
	test('application shell fills the viewport', async ({ page }) => {
		await page.goto('/');
		const appShell = page.getByTestId('app-shell');
		await expect(appShell).toBeVisible();
		const shellBox = await appShell.boundingBox();
		expect(shellBox).not.toBeNull();
		if (!shellBox) return;
		const viewport = page.viewportSize();
		expect(viewport).not.toBeNull();
		if (!viewport) return;
		expect(Math.abs(shellBox.width - viewport.width)).toBeLessThanOrEqual(2);
		expect(Math.abs(shellBox.height - viewport.height)).toBeLessThanOrEqual(2);
	});

	test('shows welcome screen on first load', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByText('Welcome to Corvus')).toBeVisible();
	});

	test('welcome screen shows routing description', async ({ page }) => {
		await page.goto('/');
		await expect(
			page.getByText('Your messages are automatically routed to the right agent')
		).toBeVisible();
	});

	test('mode rail shows Chat button as active', async ({ page }) => {
		await page.goto('/');
		const chatButton = modeButton(page, 'Chat');
		await expect(chatButton).toBeVisible();
		await expect(chatButton).toHaveAttribute('aria-current', 'page');
	});

	test('mode rail shows all workspace modes enabled', async ({ page }) => {
		await page.goto('/');

		for (const label of ['Agents', 'Tasks', 'Config', 'Timeline', 'Memory'] as const) {
			const btn = modeButton(page, label);
			await expect(btn).toBeVisible();
			await expect(btn).toBeEnabled();
		}
	});

	test('Tasks mode shows TaskSidebar', async ({ page }) => {
		await page.goto('/');
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--radius-default').trim() !== '',
			null,
			{ timeout: 5000 }
		);

		// Click the Tasks mode button
		const tasksButton = modeButton(page, 'Tasks');
		await expect(tasksButton).toBeEnabled();
		await tasksButton.click();

		// TaskSidebar should appear
		await expect(page.locator('aside[aria-label="Task sidebar"]')).toBeVisible();

		// Should show empty state
		await expect(page.getByText('No active tasks')).toBeVisible();
	});

	test('session sidebar shows empty state', async ({ page }) => {
		await page.goto('/');
		const emptyOrError = page.getByText(
			/No sessions yet\.|Failed to load session history\.|Loading session history\.\.\./
		);
		if ((await emptyOrError.count()) > 0) {
			await expect(emptyOrError.first()).toBeVisible();
		} else {
			await expect(page.locator('aside[aria-label="Session sidebar"]')).toBeVisible();
		}
	});

	test('session sidebar has New button', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByText('+ New')).toBeVisible();
	});

	test('session sidebar has search input', async ({ page }) => {
		await page.goto('/');
		const searchInput = page.getByPlaceholder('Search sessions...');
		await expect(searchInput).toBeVisible();
	});

	test('input bar is visible and focusable', async ({ page }) => {
		await page.goto('/');
		const input = page.getByPlaceholder('Message Corvus...');
		await expect(input).toBeVisible();
		await input.focus();
		await expect(input).toBeFocused();
	});

	test('status bar shows connection status', async ({ page }) => {
		await page.goto('/');
		// Depending on local gateway state this can be connected or reconnecting.
		// Scope to the header element (StatusBar) to avoid matching ConnectionToast
		const statusBar = page.locator('header');
		await expect(
			statusBar.getByText(/Connected|Disconnected|Connection failed|Connecting\.\.\./)
		).toBeVisible();
	});

	test('send button is disabled when input is empty', async ({ page }) => {
		await page.goto('/');
		const sendButton = page.getByRole('button', { name: /send/i });
		await expect(sendButton).toBeDisabled();
	});

	test('send button enables when input has text', async ({ page }) => {
		await page.goto('/');
		const input = page.getByPlaceholder('Message Corvus...');
		const sendButton = page.getByRole('button', { name: /send/i });

		await input.fill('Hello');
		await expect(sendButton).toBeEnabled();
	});

	test('agent domain labels visible in welcome screen', async ({ page }) => {
		await page.goto('/');
		// AGENT_NAMES minus 'general': personal, work, homelab, finance, email, docs, music, home
		for (const domain of ['personal', 'work', 'homelab', 'finance', 'email', 'docs', 'music', 'home']) {
			await expect(page.getByText(domain, { exact: true })).toBeVisible();
		}
	});

	test('status bar hides cost/context when no session data', async ({ page }) => {
		await page.goto('/');
		// With no active session, cost/context meters are hidden
		await expect(page.getByText('$0.00 / 0 tok')).not.toBeVisible();
		await expect(page.getByRole('progressbar', { name: 'Context usage' })).not.toBeVisible();
	});

	test('status bar shows session name', async ({ page }) => {
		await page.goto('/');
		const header = page.locator('header');
		await expect(header.getByText('Huginn')).toBeVisible();
	});

	test('keyboard shortcut hints are visible', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByText('Enter', { exact: true })).toBeVisible();
		await expect(page.getByText('Shift+Enter')).toBeVisible();
		await expect(page.getByText(/Cmd\+\.|Ctrl\+\./)).toBeVisible();
	});

	test('slash key focuses the input', async ({ page }) => {
		await page.goto('/');
		const input = page.getByPlaceholder('Message Corvus...');

		// Click on the page body first to ensure no element is focused
		await page.click('body');
		await page.keyboard.press('/');
		await expect(input).toBeFocused();
	});

	test('default session shows Huginn name on first load', async ({ page }) => {
		await page.goto('/');
		// Huginn appears in both the status bar and session title bar
		await expect(page.getByText('Huginn').first()).toBeVisible();
	});

	test('mode navigation has correct aria-label', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('navigation', { name: 'Mode navigation' })).toBeVisible();
	});

	test('connection toast text is valid when visible', async ({ page }) => {
		await page.goto('/');
		const toast = page.locator('[role="status"]');
		if ((await toast.count()) > 0) {
			await expect(toast).toContainText(
				/Disconnected from server|Connection error -- retrying\.\.\./
			);
		}
	});

	test('connection state does not block interaction', async ({ page }) => {
		await page.goto('/');
		const input = page.getByPlaceholder('Message Corvus...');
		await input.fill('hello');
		await expect(input).toHaveValue('hello');
	});
});

test.describe('Session Management', () => {
	test('clicking + New button resets session to welcome state', async ({ page }) => {
		await page.goto('/');
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--radius-default').trim() !== '',
			null,
			{ timeout: 5000 }
		);

		// Click + New
		await page.getByText('+ New').click();

		// Welcome screen should be visible (messages cleared)
		await expect(page.getByText('Welcome to Corvus')).toBeVisible();

		// Huginn name should be shown (appears in both status bar and session title)
		await expect(page.getByText('Huginn').first()).toBeVisible();
	});

	test('session title bar shows Huginn label by default', async ({ page }) => {
		await page.goto('/');
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--radius-default').trim() !== '',
			null,
			{ timeout: 5000 }
		);

		// Huginn appears in the ChatPanel session title bar
		await expect(page.getByText('Huginn').first()).toBeVisible();
	});

	test('+ New button is always visible in session sidebar', async ({ page }) => {
		await page.goto('/');

		const newButton = page.getByText('+ New');
		await expect(newButton).toBeVisible();

		// Should remain visible after clicking it
		await newButton.click();
		await expect(newButton).toBeVisible();
	});

	test('session sidebar search input is functional', async ({ page }) => {
		await page.goto('/');

		const searchInput = page.getByPlaceholder('Search sessions...');
		await expect(searchInput).toBeVisible();

		// Type into the search input
		await searchInput.fill('test query');
		await expect(searchInput).toHaveValue('test query');

		// Sidebar remains usable regardless of current session list state
		const emptyOrError = page.getByText(
			/No sessions yet\.|Failed to load session history\.|Loading session history\.\.\./
		);
		if ((await emptyOrError.count()) > 0) {
			await expect(emptyOrError.first()).toBeVisible();
		} else {
			await expect(page.locator('aside[aria-label="Session sidebar"]')).toBeVisible();
		}
	});
});
