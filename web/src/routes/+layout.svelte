<script lang="ts">
	import '#lib/theme.css';
	import { theme } from '#lib/theme.svelte.ts';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// Re-apply the remembered choice once the app runs (app.html applied it before the first
	// paint), so the store and the document agree.
	$effect(() => {
		theme.set(theme.mode);
	});
</script>

<svelte:head>
	<title>LustJinn</title>
</svelte:head>

{@render children()}
