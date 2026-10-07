<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AppBar from '#lib/AppBar.svelte';
	import StoryRail from '#lib/StoryRail.svelte';
	import { api } from '#lib/api.ts';
	import { Extras } from '#lib/extras.svelte.ts';

	/** The story's dials, meters and last prompt, on a screen of their own: open it from the
	 * conversation's ◐, change what you want, go back. */
	const id = $derived(page.params.id ?? '');

	let extras = $state<Extras | null>(null);
	let name = $state<string | null>(null);
	let section = $state<'dials' | 'meters' | 'prompt'>('dials');

	onMount(() => {
		const tab = page.url.searchParams.get('tab');
		if (tab === 'meters' || tab === 'prompt') section = tab;
		extras = new Extras(id);
		void extras.load();
		api
			.story(id)
			.then((s) => (name = s.name))
			.catch(() => undefined);
	});
</script>

<div class="screen">
	<AppBar title="Dials and meters" sub={name ?? undefined} back="/story/{id}" />
	<main>
		{#if extras}
			<StoryRail {extras} bind:section />
		{/if}
		<p class="muted small">
			Changes are saved as you make them and reach the story from its next turn.
		</p>
	</main>
</div>

<style>
	.screen {
		min-height: 100%;
		display: flex;
		flex-direction: column;
	}
	main {
		flex: 1;
		padding: 14px 16px calc(24px + var(--safe-bottom));
		max-width: 640px;
		width: 100%;
		margin: 0 auto;
		display: grid;
		gap: 16px;
		align-content: start;
	}
	.small {
		font-size: 0.8rem;
	}
</style>
