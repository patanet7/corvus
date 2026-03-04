import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, '.', '');
	const devRemoteUser = env.CORVUS_DEV_REMOTE_USER ?? 'user';
	const backendTarget = env.CORVUS_BACKEND_URL ?? 'http://localhost:18789';

	return {
		plugins: [tailwindcss(), sveltekit()],
		server: {
			proxy: {
				'/ws': {
					target: backendTarget,
					ws: true,
					changeOrigin: true,
					headers: {
						'X-Remote-User': devRemoteUser,
					},
				},
				'/health': {
					target: backendTarget,
					changeOrigin: true,
					headers: {
						'X-Remote-User': devRemoteUser,
					},
				},
				'/api': {
					target: backendTarget,
					changeOrigin: true,
					headers: {
						'X-Remote-User': devRemoteUser,
					},
				},
			},
		},
		build: {
			chunkSizeWarningLimit: 12000,
			rollupOptions: {
				output: {
					manualChunks(id) {
						if (
							id.includes('/node_modules/shiki/') ||
							id.includes('/node_modules/@shikijs/')
						) {
							return 'shiki';
						}
						if (id.includes('/node_modules/marked/') || id.includes('/node_modules/dompurify/')) {
							return 'markdown';
						}
						if (id.includes('/node_modules/')) {
							return 'vendor';
						}
						return undefined;
					}
				}
			}
		},
		test: {
			exclude: ['tests/e2e/**', 'tests/e2e-live/**', 'node_modules/**'],
		},
	};
});
