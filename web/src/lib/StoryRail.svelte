<script lang="ts">
	import DialControl from '#lib/DialControl.svelte';
	import type { Extras } from '#lib/extras.svelte.ts';

	/** Beside the conversation: the dials, the meters, the last prompt and the running cost.
	 * A column on the desktop, the ◐ sheet on a phone. */
	let { extras, section = $bindable('dials') }: { extras: Extras; section?: Section } = $props();

	type Section = 'dials' | 'meters' | 'prompt';
	const sections: { id: Section; label: string }[] = [
		{ id: 'dials', label: 'Dials' },
		{ id: 'meters', label: 'Meters' },
		{ id: 'prompt', label: 'This prompt' }
	];

	// --- meters -------------------------------------------------------------------------------
	let adding = $state(false);
	let name = $state('');
	let start = $state(0);
	let max = $state(100);
	let means = $state('');
	let setting = $state<string | null>(null);
	let setTo = $state(0);

	async function add(event: SubmitEvent) {
		event.preventDefault();
		if (!name.trim()) return;
		const ok = await extras.addTracker({
			name: name.trim(),
			value: start,
			max,
			means: means.trim() || null
		});
		if (ok) {
			adding = false;
			name = '';
			start = 0;
			max = 100;
			means = '';
		}
	}

	function money(cost: string | undefined): string {
		if (cost === undefined) return '—';
		const n = Number(cost);
		if (n === 0) return '$0';
		return n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`;
	}

	function bar(value: number, maximum: number): number {
		return maximum > 0 ? Math.min(100, Math.max(0, (value / maximum) * 100)) : 0;
	}

	function trim(n: number): string {
		return Number.isInteger(n) ? String(n) : n.toFixed(1);
	}
</script>

<div class="rail">
	<nav class="tabs" aria-label="Story settings">
		{#each sections as s (s.id)}
			<button type="button" class:on={section === s.id} onclick={() => (section = s.id)}
				>{s.label}</button
			>
		{/each}
	</nav>

	{#if !extras.loaded}
		<p class="muted small">Reading…</p>
	{:else if section === 'dials'}
		<div class="stack big">
			{#each extras.dials.filter((d) => d.enabled) as sd (sd.key)}
				{@const dial = extras.dial(sd.key)}
				{#if dial}
					<DialControl
						{dial}
						setting={sd}
						onset={(value) => extras.setDial(sd.key, value)}
						onclear={() => extras.clearDial(sd.key)}
					/>
				{/if}
			{/each}
			<p class="muted small">
				A dial reaches the prompt or the sampler from the next turn, never the transcript. This
				story only.
			</p>
		</div>
	{:else if section === 'meters'}
		<div class="stack">
			{#if extras.trackers.length === 0 && !adding}
				<p class="muted small">
					No meters. A meter is a number the story keeps — trust, heat, suspicion — that the model
					moves a little each turn and the app reads back. A meter the model can see is a meter it
					writes towards.
				</p>
			{/if}
			{#each extras.trackers as t (t.id)}
				<div class="meter">
					<div class="mhead">
						<b>{t.name}</b>
						<span class="mono">
							{trim(t.value)}/{trim(t.max)}
							{#if t.delta !== 0}
								<span class:up={t.delta > 0} class:down={t.delta < 0}
									>{t.delta > 0 ? '+' : ''}{trim(t.delta)}</span
								>
							{/if}
						</span>
					</div>
					<div class="bar"><i style:width="{bar(t.value, t.max)}%"></i></div>
					<div class="mfoot">
						<span class="muted"
							>{t.note ?? t.means ?? '—'}{t.updated_at_sequence
								? ` · turn ${t.updated_at_sequence}`
								: ''}</span
						>
						{#if setting === t.name}
							<form
								class="setrow"
								onsubmit={(e) => {
									e.preventDefault();
									extras.setTracker(t.name, setTo);
									setting = null;
								}}
							>
								<input
									class="input tiny"
									id="set-{t.id}"
									type="number"
									min="0"
									max={t.max}
									step="any"
									bind:value={setTo}
									aria-label="New value"
								/>
								<button type="submit" class="btn tiny primary">Set</button>
								<button type="button" class="btn tiny ghost" onclick={() => (setting = null)}
									>Cancel</button
								>
							</form>
						{:else}
							<span class="acts">
								<button
									type="button"
									class="link"
									onclick={() => {
										setting = t.name;
										setTo = t.value;
									}}>Set</button
								>
								<button
									type="button"
									class="link danger"
									onclick={() => extras.removeTracker(t.name)}>Remove</button
								>
							</span>
						{/if}
					</div>
				</div>
			{/each}
			{#if adding}
				<form class="add" onsubmit={add}>
					<label class="field"
						><span>Name</span><input
							class="input"
							id="meter-name"
							type="text"
							bind:value={name}
							maxlength="120"
							required
							placeholder="Trust"
						/></label
					>
					<div class="two">
						<label class="field"
							><span>Starts at</span><input
								class="input"
								id="meter-start"
								type="number"
								step="any"
								min="0"
								bind:value={start}
							/></label
						>
						<label class="field"
							><span>Out of</span><input
								class="input"
								id="meter-max"
								type="number"
								step="any"
								min="1"
								bind:value={max}
							/></label
						>
					</div>
					<label class="field"
						><span>What it measures (optional)</span><input
							class="input"
							id="meter-means"
							type="text"
							bind:value={means}
							maxlength="500"
							placeholder="how far she trusts Rowan"
						/></label
					>
					<div class="two">
						<button type="submit" class="btn primary">Add meter</button>
						<button type="button" class="btn ghost" onclick={() => (adding = false)}>Cancel</button>
					</div>
				</form>
			{:else}
				<button type="button" class="btn ghost" onclick={() => (adding = true)}>Add a meter</button>
			{/if}
		</div>
	{:else}
		<div class="stack">
			{#if extras.context}
				{@const ctx = extras.context}
				<h4>The last prompt</h4>
				{#each ctx.layers as layer (layer.name)}
					<div class="layer">
						<span>{layer.name}{layer.dropped ? ` (${layer.dropped} dropped)` : ''}</span>
						<span class="mono">{layer.tokens.toLocaleString()}</span>
						<i
							><b
								style:width="{ctx.budget
									? (layer.tokens / ctx.budget) * 100
									: (layer.tokens / Math.max(ctx.total, 1)) * 100}%"
							></b></i
						>
					</div>
				{/each}
				<p class="mono small total">
					total {ctx.total.toLocaleString()}{ctx.budget ? ` / ${ctx.budget.toLocaleString()}` : ''}
					{#if extras.audit?.turns[0]?.prompt_tokens}
						· billed {extras.audit.turns[0].prompt_tokens.toLocaleString()}
					{/if}
				</p>
			{:else}
				<p class="muted small">
					No reply yet. After the first one, this shows what the prompt was built from.
				</p>
			{/if}
			{#if extras.spend}
				<h4>This story</h4>
				<div class="cost">
					<span>Calls</span><b>{extras.spend.calls}</b>
					<span>Cost</span><b>{money(extras.spend.cost)}</b>
					<span>Rerolled away</span><b class="warn">{money(extras.spend.discarded_cost)}</b>
					{#if extras.spend.unpriced}<span>Unpriced calls</span><b>{extras.spend.unpriced}</b>{/if}
					{#if extras.spend.cached_share !== null}
						<span>Cached share</span><b>{Math.round(extras.spend.cached_share * 100)}%</b>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.rail {
		display: grid;
		gap: 14px;
		align-content: start;
		min-width: 0;
	}
	.tabs {
		display: flex;
		gap: 2px;
		padding: 3px;
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.tabs button {
		flex: 1;
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--fg-2);
		font-size: 0.8rem;
		font-weight: 500;
		padding: 6px 8px;
		min-height: 34px;
		border-radius: var(--r-pill);
	}
	.tabs button.on {
		background: var(--gold);
		color: var(--gold-ink);
	}
	.stack {
		display: grid;
		gap: 12px;
	}
	.stack.big {
		gap: 20px;
	}
	.small {
		font-size: 0.8rem;
	}
	h4 {
		font-size: 0.72rem;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--muted);
		font-weight: 600;
	}
	.meter {
		display: grid;
		gap: 6px;
		padding: 10px 12px;
		border-radius: var(--r-s);
		background: var(--surface);
		border: 1px solid var(--line);
	}
	.mhead {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		align-items: baseline;
	}
	.mhead b {
		font-weight: 600;
	}
	.mono {
		font-family: var(--font-mono);
		font-size: 0.8rem;
	}
	.up {
		color: var(--ok);
	}
	.down {
		color: var(--danger);
	}
	.bar {
		height: 8px;
		border-radius: 4px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.bar i {
		display: block;
		height: 100%;
		border-radius: 4px;
		background: linear-gradient(90deg, var(--gold-2), var(--gold));
		transition: width 0.3s ease;
	}
	.mfoot {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		align-items: center;
		font-size: 0.75rem;
		flex-wrap: wrap;
	}
	.acts {
		display: flex;
		gap: 4px;
	}
	.link {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--gold-text);
		font-weight: 600;
		font-size: 0.75rem;
		padding: 6px 8px;
		min-height: 32px;
	}
	.link.danger {
		color: var(--danger);
	}
	.setrow {
		display: flex;
		gap: 6px;
		align-items: center;
	}
	.input.tiny {
		width: 84px;
		min-height: 34px;
		padding: 6px 8px;
	}
	.btn.tiny {
		min-height: 34px;
		padding: 4px 12px;
		font-size: 0.8rem;
	}
	.add {
		display: grid;
		gap: 10px;
		padding: 12px;
		border-radius: var(--r-s);
		background: var(--surface);
		border: 1px solid var(--line);
	}
	.two {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.layer {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 2px 8px;
		font-size: 0.82rem;
		color: var(--fg-2);
	}
	.layer i {
		grid-column: 1 / -1;
		display: block;
		height: 4px;
		border-radius: 2px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.layer i b {
		display: block;
		height: 100%;
		background: var(--gold-2);
	}
	.total {
		color: var(--muted);
	}
	.cost {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 4px 12px;
		font-size: 0.88rem;
		color: var(--fg-2);
		font-variant-numeric: tabular-nums;
	}
	.cost b {
		font-weight: 600;
		color: var(--fg);
	}
	.cost .warn {
		color: var(--warn);
	}
</style>
