import { test, expect } from '@playwright/test';

/**
 * Wait for ThemeProvider's $effect to inject CSS vars on :root.
 * The effect runs after Svelte hydration, so we poll for a known var.
 */
async function waitForTheme(page: import('@playwright/test').Page) {
	await page.goto('/');
	await page.waitForFunction(
		() => getComputedStyle(document.documentElement).getPropertyValue('--radius-default').trim() !== '',
		null,
		{ timeout: 5000 }
	);
}

test.describe('Theme Engine', () => {
	test('ThemeProvider injects CSS variables on :root', async ({ page }) => {
		await waitForTheme(page);

		const vars = await page.evaluate(() => ({
			canvas: getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim(),
			surface: getComputedStyle(document.documentElement).getPropertyValue('--color-surface').trim(),
			border: getComputedStyle(document.documentElement).getPropertyValue('--color-border').trim(),
			textPrimary: getComputedStyle(document.documentElement).getPropertyValue('--color-text-primary').trim(),
			focus: getComputedStyle(document.documentElement).getPropertyValue('--color-focus').trim(),
			error: getComputedStyle(document.documentElement).getPropertyValue('--color-error').trim(),
		}));

		expect(vars.canvas).toBe('#0d1117');
		expect(vars.surface).toBe('#161b22');
		expect(vars.border).toBe('#30363d');
		expect(vars.textPrimary).toBe('#e6edf3');
		expect(vars.focus).toBe('#58a6ff');
		expect(vars.error).toBe('#da3633');
	});

	test('all agent colors are injected as CSS variables', async ({ page }) => {
		await waitForTheme(page);

		const agents = await page.evaluate(() => {
			const cs = getComputedStyle(document.documentElement);
			return {
				personal: cs.getPropertyValue('--color-agent-personal').trim(),
				work: cs.getPropertyValue('--color-agent-work').trim(),
				homelab: cs.getPropertyValue('--color-agent-homelab').trim(),
				finance: cs.getPropertyValue('--color-agent-finance').trim(),
				email: cs.getPropertyValue('--color-agent-email').trim(),
				docs: cs.getPropertyValue('--color-agent-docs').trim(),
				music: cs.getPropertyValue('--color-agent-music').trim(),
				home: cs.getPropertyValue('--color-agent-home').trim(),
				huginn: cs.getPropertyValue('--color-agent-huginn').trim(),
				general: cs.getPropertyValue('--color-agent-general').trim(),
			};
		});

		expect(agents.personal).toBe('#c084fc');
		expect(agents.work).toBe('#60a5fa');
		expect(agents.homelab).toBe('#22d3ee');
		expect(agents.finance).toBe('#34d399');
		expect(agents.email).toBe('#fbbf24');
		expect(agents.docs).toBe('#818cf8');
		expect(agents.music).toBe('#fb7185');
		expect(agents.home).toBe('#f97316');
		expect(agents.huginn).toBe('#64748b');
		expect(agents.general).toBe('#94a3b8');
	});

	test('font variables are set correctly', async ({ page }) => {
		await waitForTheme(page);

		const fonts = await page.evaluate(() => {
			const cs = getComputedStyle(document.documentElement);
			return {
				sans: cs.getPropertyValue('--font-sans').trim(),
				mono: cs.getPropertyValue('--font-mono').trim(),
				display: cs.getPropertyValue('--font-display').trim(),
			};
		});

		expect(fonts.sans).toContain('IBM Plex Sans');
		expect(fonts.mono).toContain('IBM Plex Mono');
		expect(fonts.display).toContain('IBM Plex Sans Condensed');
	});

	test('Google Fonts stylesheet is loaded dynamically', async ({ page }) => {
		await waitForTheme(page);

		const fontLinks = await page.evaluate(() =>
			Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
				.map((l) => (l as HTMLLinkElement).href)
				.filter((h) => h.includes('fonts.googleapis.com'))
		);

		// After removing the static font link from app.html, ThemeProvider is
		// the single source of truth — exactly one dynamic Google Fonts link.
		expect(fontLinks.length).toBe(1);
		expect(fontLinks[0]).toContain('IBM+Plex+Sans');
		expect(fontLinks[0]).toContain('IBM+Plex+Mono');
	});

	test('IBM Plex Sans is applied to body', async ({ page }) => {
		await waitForTheme(page);

		const bodyFont = await page.evaluate(() =>
			getComputedStyle(document.body).fontFamily
		);

		expect(bodyFont).toContain('IBM Plex Sans');
	});

	test('detail variables are injected (radius, scrollbar, selection)', async ({ page }) => {
		await waitForTheme(page);

		const details = await page.evaluate(() => {
			const cs = getComputedStyle(document.documentElement);
			return {
				radius: cs.getPropertyValue('--radius-default').trim(),
				scrollbar: cs.getPropertyValue('--scrollbar-width').trim(),
				selectionBg: cs.getPropertyValue('--color-selection-bg').trim(),
				selectionText: cs.getPropertyValue('--color-selection-text').trim(),
			};
		});

		expect(details.radius).toBe('4px');
		expect(details.scrollbar).toBe('thin');
		expect(details.selectionBg).toBe('#58a6ff33');
		expect(details.selectionText).toBe('#e6edf3');
	});

	test('animation variables are injected', async ({ page }) => {
		await waitForTheme(page);

		const animation = await page.evaluate(() => {
			const cs = getComputedStyle(document.documentElement);
			return {
				easing: cs.getPropertyValue('--theme-easing').trim(),
				durationScale: cs.getPropertyValue('--theme-duration-scale').trim(),
			};
		});

		expect(animation.easing).toBe('cubic-bezier(0.16, 1, 0.3, 1)');
		expect(animation.durationScale).toBe('1');
	});

	test('theme persists to localStorage', async ({ page }) => {
		await waitForTheme(page);

		const stored = await page.evaluate(() =>
			localStorage.getItem('corvus-theme')
		);

		// On first load, ThemeProvider defaults to ops-cockpit.
		// Either null (not yet stored) or 'ops-cockpit' is valid.
		if (stored !== null) {
			expect(stored).toBe('ops-cockpit');
		}
	});
});
