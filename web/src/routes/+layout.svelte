<script lang="ts">
	import '#lib/theme.css';
	import { onMount } from 'svelte';
	import SignIn from '#lib/SignIn.svelte';
	import Toasts from '#lib/Toasts.svelte';
	import Waking from '#lib/Waking.svelte';
	import { server } from '#lib/health.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { theme } from '#lib/theme.svelte.ts';
	import { dev } from '$app/env';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// Re-apply the remembered choice once the app runs (app.html applied it before the first
	// paint), so the store and the document agree.
	$effect(() => {
		theme.set(theme.mode);
	});

	// The static site opens instantly; the API may be asleep. Knock first, then show the app.
	onMount(() => {
		void server.wake();
		// The offline shell, in a real build only: in the dev server a worker serves stale shells.
		if (!dev && 'serviceWorker' in navigator) {
			void navigator.serviceWorker.register('/service-worker.js', { type: 'module' });
		}
	});
</script>

<svelte:head>
	<title>LustJinn</title>
</svelte:head>

{#if server.state !== 'up'}
	<Waking />
{:else if !session.signedIn}
	<SignIn />
{:else}
	{@render children()}
{/if}
<Toasts />
