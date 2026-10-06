<script lang="ts">
	import type { Snippet } from 'svelte';
	import Lamp from '#lib/Lamp.svelte';

	/** The bar at the top of a screen: a back arrow or the mark, a title with a line under it,
	 * and whatever actions the screen puts on the right. */
	let {
		title,
		sub,
		back,
		mark = false,
		actions
	}: { title: string; sub?: string; back?: string; mark?: boolean; actions?: Snippet } = $props();
</script>

<header class="bar">
	{#if back}
		<a class="back" href={back} aria-label="Back">‹</a>
	{:else if mark}
		<Lamp size={30} />
	{/if}
	<div class="title">
		<h1>{title}</h1>
		{#if sub}<span class="sub">{sub}</span>{/if}
	</div>
	<div class="grow"></div>
	{#if actions}{@render actions()}{/if}
</header>

<style>
	.bar {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: calc(10px + var(--safe-top)) 14px 10px;
		position: sticky;
		top: 0;
		z-index: 10;
		background: color-mix(in srgb, var(--bg) 86%, transparent);
		backdrop-filter: blur(14px);
		border-bottom: 1px solid var(--line);
		min-height: 56px;
	}
	.back {
		text-decoration: none;
		color: var(--fg-2);
		font-size: 1.7rem;
		line-height: 1;
		width: 36px;
		height: 36px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		margin-left: -8px;
	}
	.title {
		min-width: 0;
		display: grid;
	}
	h1 {
		font-size: 1.05rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.sub {
		font-size: 0.74rem;
		color: var(--muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.grow {
		flex: 1;
	}
</style>
