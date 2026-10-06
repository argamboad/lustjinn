<script lang="ts">
	import type { Tracker } from '#lib/api.ts';

	/** The meters as pills above the composer: a bar and the last delta each. Tap to open them. */
	let { trackers, onopen }: { trackers: Tracker[]; onopen: () => void } = $props();

	function trim(n: number): string {
		return Number.isInteger(n) ? String(n) : n.toFixed(1);
	}
</script>

{#if trackers.length > 0}
	<div class="strip">
		{#each trackers as t (t.id)}
			<button type="button" class="pill" onclick={onopen} title={t.note ?? t.name}>
				<b>{t.name}</b>
				<i style:--v="{t.max > 0 ? Math.min(100, (t.value / t.max) * 100) : 0}%"></i>
				<span class="mono">{trim(t.value)}</span>
				{#if t.delta !== 0}
					<span class="mono" class:up={t.delta > 0} class:down={t.delta < 0}
						>{t.delta > 0 ? '+' : ''}{trim(t.delta)}</span
					>
				{/if}
			</button>
		{/each}
	</div>
{/if}

<style>
	.strip {
		display: flex;
		gap: 8px;
		padding: 2px 10px 6px;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.pill {
		flex: none;
		display: inline-flex;
		gap: 8px;
		align-items: center;
		padding: 6px 10px;
		border-radius: var(--r-pill);
		background: var(--surface);
		border: 1px solid var(--line);
		color: var(--fg);
		font-size: 0.74rem;
		min-height: 32px;
	}
	.pill b {
		font-weight: 600;
	}
	.pill i {
		display: block;
		width: 46px;
		height: 5px;
		border-radius: 3px;
		background: var(--surface-2);
		position: relative;
		overflow: hidden;
	}
	.pill i::after {
		content: '';
		position: absolute;
		inset: 0 auto 0 0;
		width: var(--v);
		background: var(--gold);
	}
	.mono {
		font-family: var(--font-mono);
	}
	.up {
		color: var(--ok);
	}
	.down {
		color: var(--danger);
	}
</style>
