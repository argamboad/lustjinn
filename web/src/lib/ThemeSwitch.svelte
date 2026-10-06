<script lang="ts">
	import { theme, type ThemeMode } from '#lib/theme.svelte.ts';

	const modes: { mode: ThemeMode; label: string }[] = [
		{ mode: 'system', label: 'System' },
		{ mode: 'dark', label: 'Dark' },
		{ mode: 'light', label: 'Light' }
	];
</script>

<div class="seg" role="group" aria-label="Theme">
	{#each modes as { mode, label } (mode)}
		<button type="button" aria-pressed={theme.mode === mode} onclick={() => theme.set(mode)}>
			{label}
		</button>
	{/each}
</div>

<style>
	.seg {
		display: inline-flex;
		padding: 3px;
		gap: 2px;
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	button {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--fg-2);
		font-size: 0.85rem;
		font-weight: 500;
		padding: 6px 12px;
		min-height: 32px;
		border-radius: var(--r-pill);
	}
	button[aria-pressed='true'] {
		background: var(--gold);
		color: var(--gold-ink);
	}
</style>
