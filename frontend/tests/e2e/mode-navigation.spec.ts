import { test, expect, type Page } from '@playwright/test';

/**
 * Wait for ThemeProvider's $effect to inject CSS vars on :root.
 * The effect runs after Svelte hydration, so we poll for a known var.
 */
async function waitForTheme(page: Page) {
	await page.goto('/');
	await page.waitForFunction(
		() => getComputedStyle(document.documentElement).getPropertyValue('--radius-default').trim() !== '',
		null,
		{ timeout: 5000 }
	);
}

function modeButton(page: Page, label: 'Chat' | 'Agents' | 'Tasks' | 'Config' | 'Timeline' | 'Memory') {
	return page
		.getByRole('navigation', { name: 'Mode navigation' })
		.getByRole('button', { name: label, exact: true });
}

test.describe('Mode Navigation E2E', () => {
	test.describe('Chat mode (default)', () => {
		test('Chat mode is the default active mode', async ({ page }) => {
			await waitForTheme(page);

			const chatButton = modeButton(page, 'Chat');
			await expect(chatButton).toHaveAttribute('aria-current', 'page');
		});

		test('Chat mode shows SessionSidebar', async ({ page }) => {
			await waitForTheme(page);

			const sidebar = page.locator('aside[aria-label="Session sidebar"]');
			await expect(sidebar).toBeVisible();
		});

		test('Chat mode shows ChatPanel with welcome screen', async ({ page }) => {
			await waitForTheme(page);

			await expect(page.getByText('Welcome to Corvus')).toBeVisible();
			await expect(page.getByPlaceholder('Message Corvus...')).toBeVisible();
		});

		test('Chat mode shows both SessionSidebar and ChatPanel simultaneously', async ({ page }) => {
			await waitForTheme(page);

			await expect(page.locator('aside[aria-label="Session sidebar"]')).toBeVisible();
			await expect(page.getByText('Welcome to Corvus')).toBeVisible();
			await expect(page.getByPlaceholder('Message Corvus...')).toBeVisible();
		});
	});

	test.describe('Tasks mode', () => {
		test('clicking Tasks mode shows TaskSidebar', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();

			const taskSidebar = page.locator('aside[aria-label="Task sidebar"]');
			await expect(taskSidebar).toBeVisible();
		});

		test('Tasks mode shows empty state message', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();

			const taskSidebar = page.locator('aside[aria-label="Task sidebar"]');
			await expect(taskSidebar.getByText('No active tasks')).toBeVisible();
		});

		test('Tasks mode hides SessionSidebar but keeps ChatPanel visible', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();

			await expect(page.locator('aside[aria-label="Session sidebar"]')).not.toBeVisible();
			await expect(page.getByText('Welcome to Corvus')).toBeVisible();
			await expect(page.getByPlaceholder('Message Corvus...')).toBeVisible();
		});

		test('Tasks mode sets aria-current on Tasks button', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();

			const tasksButton = modeButton(page, 'Tasks');
			await expect(tasksButton).toHaveAttribute('aria-current', 'page');

			const chatButton = modeButton(page, 'Chat');
			await expect(chatButton).not.toHaveAttribute('aria-current', 'page');
		});

		test('Tasks mode keeps chat composer available in main area', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();

			await expect(page.getByPlaceholder('Message Corvus...')).toBeVisible();
		});
	});

	test.describe('Agents mode', () => {
		test('clicking Agents mode shows Agent directory and workspace', async ({ page }) => {
			await waitForTheme(page);
			await modeButton(page, 'Agents').click();

			await expect(page.locator('aside[aria-label="Agent directory"]')).toBeVisible();
			await expect(page.getByText(/Agent Workspace|Workspace/)).toBeVisible();
		});
	});

	test.describe('Config mode', () => {
		test('clicking Config mode shows ThemeSelector', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Config').click();

			await expect(page.getByText('Settings')).toBeVisible();
		});

		test('Config mode shows Appearance section with theme options', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Config').click();

			await expect(page.getByText('Appearance')).toBeVisible();
			await expect(page.getByText('Modern Ops Cockpit')).toBeVisible();
			await expect(page.getByText('Retro Terminal')).toBeVisible();
			await expect(page.getByText('Dark Fantasy')).toBeVisible();
		});

		test('Config mode hides SessionSidebar and ChatPanel', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Config').click();

			await expect(page.locator('aside[aria-label="Session sidebar"]')).not.toBeVisible();
			await expect(page.getByText('Welcome to Corvus')).not.toBeVisible();
		});

		test('Config mode sets aria-current on Config button', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Config').click();

			const configButton = modeButton(page, 'Config');
			await expect(configButton).toHaveAttribute('aria-current', 'page');

			const chatButton = modeButton(page, 'Chat');
			await expect(chatButton).not.toHaveAttribute('aria-current', 'page');
		});
	});

	test.describe('Additional modes', () => {
		test('Timeline mode is enabled and shows trace panel', async ({ page }) => {
			await waitForTheme(page);

			const timelineButton = modeButton(page, 'Timeline');
			await expect(timelineButton).toBeEnabled();
			await timelineButton.click();
			await expect(timelineButton).toHaveAttribute('aria-current', 'page');
			await expect(page.locator('section[aria-label="Trace timeline panel"]')).toBeVisible();
		});

		test('Memory mode is enabled and shows memory workspace panel', async ({ page }) => {
			await waitForTheme(page);

			const memoryButton = modeButton(page, 'Memory');
			await expect(memoryButton).toBeEnabled();
			await memoryButton.click();
			await expect(memoryButton).toHaveAttribute('aria-current', 'page');
			await expect(page.locator('section[aria-label="Memory workspace panel"]')).toBeVisible();
		});
	});

	test.describe('Mode switching round trips', () => {
		test('switching from Tasks back to Chat restores full chat view', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();
			await expect(page.locator('aside[aria-label="Task sidebar"]')).toBeVisible();
			await expect(page.locator('aside[aria-label="Session sidebar"]')).not.toBeVisible();
			await expect(page.getByPlaceholder('Message Corvus...')).toBeVisible();

			await modeButton(page, 'Chat').click();
			await expect(page.locator('aside[aria-label="Session sidebar"]')).toBeVisible();
			await expect(page.getByText('Welcome to Corvus')).toBeVisible();
			await expect(page.getByPlaceholder('Message Corvus...')).toBeVisible();

			await expect(page.locator('aside[aria-label="Task sidebar"]')).not.toBeVisible();
		});

		test('switching from Config back to Chat restores full chat view', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Config').click();
			await expect(page.getByText('Settings')).toBeVisible();

			await modeButton(page, 'Chat').click();
			await expect(page.locator('aside[aria-label="Session sidebar"]')).toBeVisible();
			await expect(page.getByText('Welcome to Corvus')).toBeVisible();
			await expect(page.getByText('Settings')).not.toBeVisible();
		});

		test('cycling through all enabled modes and back to Chat', async ({ page }) => {
			await waitForTheme(page);

			await modeButton(page, 'Tasks').click();
			await expect(page.locator('aside[aria-label="Task sidebar"]')).toBeVisible();

			await modeButton(page, 'Memory').click();
			await expect(page.locator('section[aria-label="Memory workspace panel"]')).toBeVisible();
			await expect(page.locator('aside[aria-label="Task sidebar"]')).not.toBeVisible();

			await modeButton(page, 'Config').click();
			await expect(page.getByText('Settings')).toBeVisible();
			await expect(page.locator('section[aria-label="Memory workspace panel"]')).not.toBeVisible();

			await modeButton(page, 'Chat').click();
			await expect(page.getByText('Welcome to Corvus')).toBeVisible();
			await expect(page.getByText('Settings')).not.toBeVisible();
		});

		test('ModeRail is always visible regardless of active mode', async ({ page }) => {
			await waitForTheme(page);

			const modeNav = page.getByRole('navigation', { name: 'Mode navigation' });

			await expect(modeNav).toBeVisible();

			await modeButton(page, 'Tasks').click();
			await expect(modeNav).toBeVisible();

			await modeButton(page, 'Config').click();
			await expect(modeNav).toBeVisible();
		});
	});
});
