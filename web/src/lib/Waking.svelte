<script lang="ts">
	import Lamp from '#lib/Lamp.svelte';
	import { server } from '#lib/health.svelte.ts';
</script>

<main class="wake">
	<Lamp size={140} glow label="LustJinn" />
	{#if server.state === 'down'}
		<h1>The server is not answering</h1>
		<p>
			It has been more than two minutes. The app keeps trying on its own; nothing you typed is lost.
		</p>
		<button class="btn ghost" type="button" onclick={() => server.retry()}>Try again now</button>
	{:else}
		<h1>Waking the server</h1>
		<p>
			The free tier sleeps after a quiet quarter hour. The lamp breathes until it answers, usually
			in under a minute.
		</p>
	{/if}
	<div class="dots" aria-hidden="true"><i></i><i></i><i></i></div>
	<p class="muted small" aria-live="polite">
		{#if server.attempts > 0}
			{server.attempts} {server.attempts === 1 ? 'knock' : 'knocks'} so far
		{:else}
			Knocking…
		{/if}
	</p>
</main>

<style>
	.wake {
		min-height: 100%;
		display: grid;
		place-items: center;
		align-content: center;
		gap: 18px;
		padding: calc(24px + var(--safe-top)) 24px calc(24px + var(--safe-bottom));
		text-align: center;
	}
	h1 {
		font-size: 1.5rem;
	}
	p {
		color: var(--fg-2);
		max-width: 32ch;
	}
	.small {
		font-size: 0.8rem;
	}
	.dots {
		display: flex;
		gap: 6px;
	}
	.dots i {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--gold);
		animation: hop 1.2s ease-in-out infinite;
	}
	.dots i:nth-child(2) {
		animation-delay: 0.15s;
	}
	.dots i:nth-child(3) {
		animation-delay: 0.3s;
	}
	@keyframes hop {
		50% {
			transform: translateY(-6px);
			opacity: 0.5;
		}
	}
</style>
