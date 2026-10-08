<script lang="ts">
	import AppBar from '#lib/AppBar.svelte';
	import Tabs from '#lib/Tabs.svelte';
	import ThemeSwitch from '#lib/ThemeSwitch.svelte';
	import { API_URL } from '#lib/api.ts';
	import { server } from '#lib/health.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
</script>

<div class="screen">
	<AppBar title="You" mark />
	<main>
		<section class="card">
			<h2>Theme</h2>
			<p class="muted">
				Follows the system unless you choose. The choice is remembered on this device.
			</p>
			<ThemeSwitch />
		</section>
		<section class="card">
			<h2>This device</h2>
			<p class="muted">
				Signed in; the token lasts a month. Signing out forgets it here and nowhere else.
			</p>
			<button class="btn ghost" type="button" onclick={() => session.signOut()}>Sign out</button>
		</section>
		<section class="card small">
			<h2>About</h2>
			<p class="muted">API at <code>{API_URL}</code></p>
			{#if server.commit}
				<p class="muted">Server build <code>{server.commit.slice(0, 7)}</code></p>
			{/if}
		</section>
	</main>
	<Tabs />
</div>

<style>
	.screen {
		min-height: 100%;
		display: flex;
		flex-direction: column;
	}
	main {
		flex: 1;
		padding: 16px 16px 24px;
		display: grid;
		gap: 12px;
		align-content: start;
		max-width: 640px;
		width: 100%;
		margin: 0 auto;
	}
	.card {
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: var(--r-m);
		padding: 16px;
		display: grid;
		gap: 10px;
		justify-items: start;
	}
	h2 {
		font-size: 1rem;
	}
	.small p {
		font-size: 0.85rem;
	}
</style>
