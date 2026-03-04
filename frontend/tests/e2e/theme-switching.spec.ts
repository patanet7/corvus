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

/**
 * Navigate to Config mode and wait for the ThemeSelector to be visible.
 */
async function openConfigPanel(page: Page) {
	await waitForTheme(page);
	const configButton = page.getByRole('button', { name: 'Config' });
	await configButton.click();
	await expect(page.getByText('Settings')).toBeVisible();
}

/**
 * Read a set of CSS custom properties from :root.
 */
async function getCssVars(page: Page, vars: string[]): Promise<Record<string, string>> {
	return page.evaluate((varNames) => {
		const cs = getComputedStyle(document.documentElement);
		const result: Record<string, string> = {};
		for (const v of varNames) {
			result[v] = cs.getPropertyValue(v).trim();
		}
		return result;
	}, vars);
}

test.describe('Theme Switching E2E', () => {
	test('Config mode shows ThemeSelector with built-in themes listed', async ({ page }) => {
		await openConfigPanel(page);

		await expect(page.getByText('Modern Ops Cockpit')).toBeVisible();
		await expect(page.getByText('Retro Terminal')).toBeVisible();
		await expect(page.getByText('Dark Fantasy')).toBeVisible();
		await expect(page.getByText('Tactical RTS Command')).toBeVisible();
	});

	test('Ops Cockpit is the default active theme with Active badge', async ({ page }) => {
		await openConfigPanel(page);

		// The Active badge should be present next to Ops Cockpit
		const opsCockpitRow = page.locator('button', { hasText: 'Modern Ops Cockpit' });
		await expect(opsCockpitRow.getByText('Active')).toBeVisible();

		// Other themes should NOT have the Active badge
		const retroRow = page.locator('button', { hasText: 'Retro Terminal' });
		await expect(retroRow.getByText('Active')).not.toBeVisible();

		const fantasyRow = page.locator('button', { hasText: 'Dark Fantasy' });
		await expect(fantasyRow.getByText('Active')).not.toBeVisible();
	});

	test('switching to Retro Terminal updates CSS vars correctly', async ({ page }) => {
		await openConfigPanel(page);

		// Click Retro Terminal
		const retroButton = page.locator('button', { hasText: 'Retro Terminal' });
		await retroButton.click();

		// Wait for the theme effect to apply
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim() === '#000000',
			null,
			{ timeout: 5000 }
		);

		const vars = await getCssVars(page, [
			'--color-canvas',
			'--color-surface',
			'--color-border',
			'--color-text-primary',
			'--color-focus',
			'--font-sans',
			'--radius-default',
		]);

		expect(vars['--color-canvas']).toBe('#000000');
		expect(vars['--color-surface']).toBe('#0a0a0a');
		expect(vars['--color-border']).toBe('#1a3a1a');
		expect(vars['--color-text-primary']).toBe('#33ff33');
		expect(vars['--color-focus']).toBe('#33ff33');
		expect(vars['--font-sans']).toContain('Share Tech Mono');
		expect(vars['--radius-default']).toBe('0px');
	});

	test('switching to Dark Fantasy updates CSS vars correctly', async ({ page }) => {
		await openConfigPanel(page);

		// Click Dark Fantasy
		const fantasyButton = page.locator('button', { hasText: 'Dark Fantasy' });
		await fantasyButton.click();

		// Wait for the theme effect to apply
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim() === '#1a1510',
			null,
			{ timeout: 5000 }
		);

		const vars = await getCssVars(page, [
			'--color-canvas',
			'--color-surface',
			'--color-border',
			'--color-text-primary',
			'--color-focus',
			'--font-sans',
			'--radius-default',
		]);

		expect(vars['--color-canvas']).toBe('#1a1510');
		expect(vars['--color-surface']).toBe('#221c14');
		expect(vars['--color-border']).toBe('#b8860b');
		expect(vars['--color-text-primary']).toBe('#d4c5a9');
		expect(vars['--color-focus']).toBe('#daa520');
		expect(vars['--font-sans']).toContain('EB Garamond');
		expect(vars['--radius-default']).toBe('2px');
	});

	test('switching back to Ops Cockpit restores original values', async ({ page }) => {
		await openConfigPanel(page);

		// Switch to Retro Terminal first
		await page.locator('button', { hasText: 'Retro Terminal' }).click();
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim() === '#000000',
			null,
			{ timeout: 5000 }
		);

		// Now switch back to Ops Cockpit
		await page.locator('button', { hasText: 'Modern Ops Cockpit' }).click();
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim() === '#0d1117',
			null,
			{ timeout: 5000 }
		);

		const vars = await getCssVars(page, [
			'--color-canvas',
			'--color-surface',
			'--color-border',
			'--color-text-primary',
			'--color-focus',
			'--font-sans',
			'--radius-default',
		]);

		expect(vars['--color-canvas']).toBe('#0d1117');
		expect(vars['--color-surface']).toBe('#161b22');
		expect(vars['--color-border']).toBe('#30363d');
		expect(vars['--color-text-primary']).toBe('#e6edf3');
		expect(vars['--color-focus']).toBe('#58a6ff');
		expect(vars['--font-sans']).toContain('IBM Plex Sans');
		expect(vars['--radius-default']).toBe('4px');
	});

	test('Active badge moves to the selected theme', async ({ page }) => {
		await openConfigPanel(page);

		// Initially Ops Cockpit should be active
		const opsRow = page.locator('button', { hasText: 'Modern Ops Cockpit' });
		const retroRow = page.locator('button', { hasText: 'Retro Terminal' });
		const fantasyRow = page.locator('button', { hasText: 'Dark Fantasy' });

		await expect(opsRow.getByText('Active')).toBeVisible();
		await expect(retroRow.getByText('Active')).not.toBeVisible();

		// Switch to Retro Terminal
		await retroRow.click();
		await expect(retroRow.getByText('Active')).toBeVisible();
		await expect(opsRow.getByText('Active')).not.toBeVisible();
		await expect(fantasyRow.getByText('Active')).not.toBeVisible();

		// Switch to Dark Fantasy
		await fantasyRow.click();
		await expect(fantasyRow.getByText('Active')).toBeVisible();
		await expect(opsRow.getByText('Active')).not.toBeVisible();
		await expect(retroRow.getByText('Active')).not.toBeVisible();

		// Switch back to Ops Cockpit
		await opsRow.click();
		await expect(opsRow.getByText('Active')).toBeVisible();
		await expect(retroRow.getByText('Active')).not.toBeVisible();
		await expect(fantasyRow.getByText('Active')).not.toBeVisible();
	});

	test('theme choice persists in localStorage after switching', async ({ page }) => {
		await openConfigPanel(page);

		// Switch to Retro Terminal
		await page.locator('button', { hasText: 'Retro Terminal' }).click();

		// Verify localStorage was updated
		const stored = await page.evaluate(() => localStorage.getItem('corvus-theme'));
		expect(stored).toBe('retro-terminal');

		// Switch to Dark Fantasy
		await page.locator('button', { hasText: 'Dark Fantasy' }).click();
		const stored2 = await page.evaluate(() => localStorage.getItem('corvus-theme'));
		expect(stored2).toBe('dark-fantasy');

		// Switch back to Ops Cockpit
		await page.locator('button', { hasText: 'Modern Ops Cockpit' }).click();
		const stored3 = await page.evaluate(() => localStorage.getItem('corvus-theme'));
		expect(stored3).toBe('ops-cockpit');
	});

	test('theme persists across page reload', async ({ page }) => {
		await openConfigPanel(page);

		// Switch to Dark Fantasy
		await page.locator('button', { hasText: 'Dark Fantasy' }).click();
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim() === '#1a1510',
			null,
			{ timeout: 5000 }
		);

		// Reload the page
		await page.reload();
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--radius-default').trim() !== '',
			null,
			{ timeout: 5000 }
		);

		// Verify Dark Fantasy CSS vars are still applied after reload
		const vars = await getCssVars(page, ['--color-canvas', '--color-text-primary']);
		expect(vars['--color-canvas']).toBe('#1a1510');
		expect(vars['--color-text-primary']).toBe('#d4c5a9');
	});

	test('each theme shows its font family and radius in the description', async ({ page }) => {
		await openConfigPanel(page);

		const opsRow = page.locator('button', { hasText: 'Modern Ops Cockpit' });
		await expect(opsRow.getByText('IBM Plex Sans')).toBeVisible();
		await expect(opsRow.getByText('4px radius')).toBeVisible();

		const retroRow = page.locator('button', { hasText: 'Retro Terminal' });
		await expect(retroRow.getByText('Share Tech Mono')).toBeVisible();
		await expect(retroRow.getByText('0px radius')).toBeVisible();

		const fantasyRow = page.locator('button', { hasText: 'Dark Fantasy' });
		await expect(fantasyRow.getByText('EB Garamond')).toBeVisible();
		await expect(fantasyRow.getByText('2px radius')).toBeVisible();

		const rtsRow = page.locator('button', { hasText: 'Tactical RTS Command' });
		await expect(rtsRow.getByText('Rajdhani')).toBeVisible();
		await expect(rtsRow.getByText('2px radius')).toBeVisible();
	});

	test('Google Fonts stylesheet updates when theme changes', async ({ page }) => {
		await openConfigPanel(page);

		// Default theme loads IBM Plex fonts
		const fontLinks = await page.evaluate(() =>
			Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
				.map((l) => (l as HTMLLinkElement).href)
				.filter((h) => h.includes('fonts.googleapis.com'))
		);
		expect(fontLinks.length).toBeGreaterThanOrEqual(1);
		expect(fontLinks.some((h) => h.includes('IBM+Plex+Sans'))).toBe(true);

		// Switch to Retro Terminal
		await page.locator('button', { hasText: 'Retro Terminal' }).click();

		// The font variable should update to Share Tech Mono
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--font-sans').trim().includes('Share Tech Mono'),
			null,
			{ timeout: 5000 }
		);

		const newFontSans = await page.evaluate(() =>
			getComputedStyle(document.documentElement).getPropertyValue('--font-sans').trim()
		);
		expect(newFontSans).toContain('Share Tech Mono');
	});

	test('agent colors update when switching themes', async ({ page }) => {
		await openConfigPanel(page);

		// Default Ops Cockpit agent colors
		let agents = await getCssVars(page, ['--color-agent-personal', '--color-agent-homelab']);
		expect(agents['--color-agent-personal']).toBe('#c084fc');
		expect(agents['--color-agent-homelab']).toBe('#22d3ee');

		// Switch to Retro Terminal
		await page.locator('button', { hasText: 'Retro Terminal' }).click();
		await page.waitForFunction(
			() => getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim() === '#000000',
			null,
			{ timeout: 5000 }
		);

		agents = await getCssVars(page, ['--color-agent-personal', '--color-agent-homelab']);
		expect(agents['--color-agent-personal']).toBe('#cc66ff');
		expect(agents['--color-agent-homelab']).toBe('#00ffcc');
	});
});
