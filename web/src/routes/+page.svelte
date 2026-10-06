<script lang="ts">
	import ThemeSwitch from '#lib/ThemeSwitch.svelte';
	import { API_URL } from '#lib/api.ts';
</script>

<main>
	<p class="eyebrow">Step 8 · the shell</p>
	<h1>Lust<span>Jinn</span></h1>
	<p class="muted">
		The design tokens, the theme and the API client are in place. The screens come next.
	</p>
	<ThemeSwitch />
	<p class="muted api">API at <code>{API_URL}</code></p>
</main>

<style>
	main {
		min-height: 100%;
		display: grid;
		align-content: center;
		justify-items: start;
		gap: 16px;
		padding: calc(24px + var(--safe-top)) 20px calc(24px + var(--safe-bottom));
		max-width: 560px;
		margin: 0 auto;
	}
	h1 {
		font-size: clamp(2.2rem, 8vw, 3.4rem);
	}
	h1 span {
		color: var(--gold-text);
	}
	.api {
		font-size: 0.85rem;
	}
</style>
