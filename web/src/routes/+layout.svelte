<script lang="ts">
	import '#lib/theme.css';
	import { onMount } from 'svelte';
	import SignIn from '#lib/SignIn.svelte';
	import Toasts from '#lib/Toasts.svelte';
	import Waking from '#lib/Waking.svelte';
	import { server } from '#lib/health.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { theme } from '#lib/theme.svelte.ts';
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
