<script lang="ts">
	import Sheet from '#lib/Sheet.svelte';
	import { REASONS } from '#lib/reasons.ts';

	/** Pick why the reply should be written again; the reason is what makes the second attempt
	 * differ. Free text is a direction under the note, never read as the latest message. */
	let {
		open = $bindable(false),
		onreroll
	}: { open?: boolean; onreroll: (reason: string, instructions: string | null) => void } = $props();

	let reason = $state('none');
	let instructions = $state('');

	function go() {
		open = false;
		onreroll(reason, instructions.trim() || null);
		instructions = '';
		reason = 'none';
	}
</script>

<Sheet bind:open title="Write it again" hint="the old reply is kept, hidden">
	<div class="reasons" role="radiogroup" aria-label="Reason">
		{#each REASONS as r (r.value)}
			<button
				type="button"
				role="radio"
				aria-checked={reason === r.value}
				class:on={reason === r.value}
				onclick={() => (reason = r.value)}
			>
				<b>{r.label}</b>
				<small>{r.describe}</small>
			</button>
		{/each}
	</div>
	<label class="field">
		<span>Anything to add (optional)</span>
		<textarea
			class="input"
			id="reroll-instructions"
			rows="2"
			bind:value={instructions}
			placeholder="have her refuse the money"></textarea>
	</label>
	<button class="btn primary" type="button" onclick={go}>Reroll</button>
</Sheet>

<style>
	.reasons {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: 8px;
	}
	.reasons button {
		display: grid;
		gap: 2px;
		text-align: left;
		padding: 10px 12px;
		border-radius: var(--r-s);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--fg);
		min-height: 56px;
	}
	.reasons button.on {
		border-color: var(--gold);
		box-shadow: 0 0 0 3px var(--gold-soft);
	}
	.reasons b {
		font-weight: 600;
		font-size: 0.88rem;
	}
	.reasons small {
		color: var(--muted);
		font-size: 0.74rem;
		line-height: 1.3;
	}
	textarea.input {
		font-family: var(--font-prose);
		resize: vertical;
	}
</style>
