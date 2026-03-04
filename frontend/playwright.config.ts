import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: 'tests/e2e',
	timeout: 30_000,
	retries: 0,
	reporter: 'list',
	webServer: {
		command:
			'env -u NO_COLOR VITE_DISABLE_BACKEND=1 pnpm run build && env -u NO_COLOR VITE_DISABLE_BACKEND=1 pnpm run preview',
		port: 4173,
		reuseExistingServer: false,
		timeout: 120_000
	},
	use: {
		baseURL: 'http://localhost:4173',
		// Only test Chromium for now
		browserName: 'chromium'
	}
});
