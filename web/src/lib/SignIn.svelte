<script lang="ts">
	import Lamp from '#lib/Lamp.svelte';
	import ThemeSwitch from '#lib/ThemeSwitch.svelte';
	import { ApiError, Unreachable } from '#lib/api.ts';
	import { server } from '#lib/health.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	let username = $state('');
	let password = $state('');
	let busy = $state(false);
	let problem = $state<string | null>(null);

	const ready = $derived(username.trim().length > 0 && password.length > 0 && !busy);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!ready) return;
		busy = true;
		problem = null;
		try {
			await session.signIn(username.trim(), password);
		} catch (error) {
			if (error instanceof ApiError) problem = error.message;
			else if (error instanceof Unreachable) {
				problem = 'The server went quiet. Waking it again.';
				server.lost();
			} else problem = 'Something went wrong. Try again.';
		} finally {
			busy = false;
		}
	}
</script>

<main class="sign-in">
	<form onsubmit={submit} autocomplete="on">
		<div class="head">
			<Lamp size={92} label="LustJinn" />
			<h1>Lust<span>Jinn</span></h1>
			<p class="muted">Sign in once. This device stays signed in for a month.</p>
		</div>
		{#if session.note}
			<p class="note" role="status">{session.note}</p>
		{/if}
		<label class="field">
			<span>Name</span>
			<input
				class="input"
				id="username"
				name="username"
				type="text"
				autocomplete="username"
				autocapitalize="none"
				spellcheck="false"
				bind:value={username}
				required
			/>
		</label>
		<label class="field">
			<span>Password</span>
			<input
				class="input"
				id="password"
				name="password"
				type="password"
				autocomplete="current-password"
				bind:value={password}
				required
			/>
		</label>
		{#if problem}
			<p class="problem" role="alert">{problem}</p>
		{/if}
		<button class="btn primary" type="submit" disabled={!ready}>
			{busy ? 'Signing in…' : 'Sign in'}
		</button>
		<div class="foot">
			<ThemeSwitch />
		</div>
	</form>
</main>

<style>
	.sign-in {
		min-height: 100%;
		display: grid;
		place-items: center;
		padding: calc(24px + var(--safe-top)) 20px calc(24px + var(--safe-bottom));
	}
	form {
		width: 100%;
		max-width: 380px;
		display: grid;
		gap: 16px;
	}
	.head {
		display: grid;
		justify-items: center;
		gap: 10px;
		text-align: center;
		margin-bottom: 8px;
	}
	h1 {
		font-size: 2rem;
	}
	h1 span {
		color: var(--gold-text);
	}
	.note {
		padding: 10px 14px;
		border-radius: var(--r-s);
		background: var(--gold-soft);
		color: var(--fg-2);
		font-size: 0.9rem;
	}
	.problem {
		color: var(--danger);
		font-size: 0.9rem;
	}
	.foot {
		display: flex;
		justify-content: center;
		margin-top: 8px;
	}
</style>
