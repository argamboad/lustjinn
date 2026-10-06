// The offline shell. The built app and the static files are cached on install, so the installed
// app opens instantly, and a navigation falls back to the cached shell when the network is away.
// API calls are never cached here: the stories come from the API, or they wait.

import { version } from '$app/env';
import { assets, immutable } from '$app/manifest';
import { self } from '$app/service-worker';

const CACHE = `lustjinn-${version}`;
const ASSETS = [...immutable, ...assets].map((file) => file.path);

self.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll(ASSETS))
			.then(() => self.skipWaiting())
	);
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
			)
			.then(() => self.clients.claim())
	);
});

self.addEventListener('fetch', (event) => {
	const { request } = event;
	if (request.method !== 'GET') return;
	const url = new URL(request.url);
	if (url.origin !== self.location.origin) return; // the API, the fonts: never from here

	event.respondWith(
		(async () => {
			const cache = await caches.open(CACHE);
			if (ASSETS.includes(url.pathname)) {
				const hit = await cache.match(url.pathname);
				if (hit) return hit;
			}
			try {
				const fresh = await fetch(request);
				if (request.mode === 'navigate' && fresh.ok) await cache.put('/', fresh.clone());
				return fresh;
			} catch {
				if (request.mode === 'navigate') {
					const shell = (await cache.match('/')) ?? (await cache.match('/index.html'));
					if (shell) return shell;
				}
				const hit = await cache.match(request);
				if (hit) return hit;
				return new Response('Offline', { status: 503, statusText: 'Offline' });
			}
		})()
	);
});
