import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

// `npm run dev` against any API without CORS: with API_PROXY set (a URL), the dev server forwards
// /api-proxy/* to it and the app calls /api-proxy instead of VITE_API_URL. The browser then only
// talks to the dev server, so the API's CORS list never has to name localhost. The debug entries
// in .vscode/launch.json use it for both the local API and staging. Only the URL travels through
// the environment: Git Bash rewrites a value starting with `/` into a Windows path.
const PROXY_PREFIX = '/api-proxy';

export default defineConfig(({ mode }) => {
	const target = loadEnv(mode, '.', 'API_PROXY').API_PROXY;
	return {
		define: target ? { 'import.meta.env.VITE_API_URL': JSON.stringify(PROXY_PREFIX) } : {},
		server: target
			? {
					proxy: {
						[PROXY_PREFIX]: {
							target,
							changeOrigin: true,
							rewrite: (path: string) => path.slice(PROXY_PREFIX.length)
						}
					}
				}
			: {},
		plugins: [
			sveltekit({
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) =>
						filename.split(/[/\\]/).includes('node_modules') ? undefined : true
				},
				// A single-page app: index.html answers every path, so /story/<id> opens on a reload.
				adapter: adapter({ fallback: 'index.html' }),
				// Registered by the layout, and only in a production build: a service worker in the dev
				// server serves stale shells and 503s once the server has been restarted.
				serviceWorker: { register: false }
			})
		],
		test: {
			expect: { requireAssertions: true },
			projects: [
				{
					extends: './vite.config.ts',
					test: {
						name: 'server',
						environment: 'node',
						include: ['src/**/*.{test,spec}.{js,ts}'],
						exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
					}
				}
			]
		}
	};
});
