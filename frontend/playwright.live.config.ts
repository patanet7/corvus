import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: 'tests/e2e-live',
	workers: 1,
	fullyParallel: false,
	timeout: 180_000,
	retries: 0,
	reporter: 'list',
	webServer: {
		command: 'env -u NO_COLOR pnpm dev --host 127.0.0.1 --port 4173',
		port: 4173,
		reuseExistingServer: true,
		timeout: 120_000
	},
	use: {
		baseURL: 'http://127.0.0.1:4173',
		browserName: 'chromium'
	}
});
