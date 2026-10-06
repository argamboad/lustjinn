<script lang="ts">
	import type { Dial, StoryDial } from '#lib/api.ts';

	/** One dial as a control: five steps for a scale, a switch for a toggle, options for a
	 * choice, comma-separated items for a list, a line for text. The text under it is the exact
	 * text the model receives for the level in force. */
	let {
		dial,
		setting,
		onset,
		onclear
	}: {
		dial: Dial;
		setting: StoryDial;
		onset: (value: string) => void;
		onclear: () => void;
	} = $props();

	const inForce = $derived(setting.effective);
	const level = $derived(
		dial.kind === 'scale' && inForce !== null ? dial.levels[Number(inForce)] : null
	);
	const option = $derived(
		dial.kind === 'choice' ? dial.options.find((o) => o.key === inForce) : null
	);
	let draft = $state('');
	let editing = $state(false);

	function listItems(value: string | null): string {
		if (!value) return '';
		try {
			const items = JSON.parse(value) as unknown;
			return Array.isArray(items) ? items.join(', ') : value;
		} catch {
			return value;
		}
	}

	function beginEdit() {
		draft = dial.kind === 'list' ? listItems(inForce) : (inForce ?? '');
		editing = true;
	}

	function commit() {
		editing = false;
		if (draft.trim()) onset(draft.trim());
		else if (setting.stored !== null) onclear();
	}
</script>

<div class="dial">
	<div class="head">
		<b>{dial.title}</b>
		<span class="now">
			{#if setting.label}{setting.label}{:else}<span class="muted">not set</span>{/if}
			{#if setting.stored !== null}
				<button type="button" class="clear" onclick={onclear} aria-label="Back to the default"
					>×</button
				>
			{/if}
		</span>
	</div>

	{#if dial.kind === 'scale'}
		<div class="steps" role="radiogroup" aria-label={dial.title}>
			{#each dial.levels as lvl, i (lvl.label)}
				<button
					type="button"
					role="radio"
					aria-checked={inForce === String(i)}
					aria-label={lvl.label}
					class:on={inForce === String(i)}
					class:after={inForce !== null && i > Number(inForce)}
					onclick={() => onset(String(i))}
				>
					<span class="lbl">{lvl.label}</span>
				</button>
			{/each}
		</div>
		<p class="help">{level ? (level.text ?? level.description ?? '') : dial.help}</p>
	{:else if dial.kind === 'toggle'}
		<div class="row">
			<p class="help grow">{dial.help}</p>
			<button
				type="button"
				class="toggle"
				role="switch"
				aria-checked={inForce === 'true'}
				aria-label={dial.title}
				onclick={() => onset(inForce === 'true' ? 'false' : 'true')}
			></button>
		</div>
	{:else if dial.kind === 'choice'}
		<div class="options">
			{#each dial.options as o (o.key)}
				<button type="button" class="opt" class:on={inForce === o.key} onclick={() => onset(o.key)}
					>{o.label}</button
				>
			{/each}
		</div>
		<p class="help">{option ? option.text : dial.help}</p>
	{:else}
		{#if editing}
			<input
				class="input"
				id="dial-{dial.key}"
				type="text"
				bind:value={draft}
				placeholder={dial.examples[0] ?? ''}
				onblur={commit}
				onkeydown={(e) => {
					if (e.key === 'Enter') commit();
					if (e.key === 'Escape') editing = false;
				}}
			/>
		{:else}
			<button type="button" class="value" onclick={beginEdit}>
				{dial.kind === 'list' ? listItems(inForce) || 'Add items…' : inForce || 'Set…'}
			</button>
		{/if}
		<p class="help">{dial.accepts ?? dial.help}</p>
	{/if}
</div>

<style>
	.dial {
		display: grid;
		gap: 8px;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 10px;
	}
	.head b {
		font-weight: 600;
	}
	.now {
		color: var(--gold-text);
		font-size: 0.85rem;
		font-weight: 500;
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.clear {
		appearance: none;
		border: 0;
		background: var(--surface-2);
		color: var(--muted);
		width: 22px;
		height: 22px;
		border-radius: 50%;
		font-size: 0.9rem;
		line-height: 1;
		display: grid;
		place-items: center;
	}
	.steps {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 4px;
		padding-bottom: 16px;
	}
	.steps button {
		appearance: none;
		border: 0;
		height: 34px;
		border-radius: 8px;
		background: var(--surface-2);
		position: relative;
	}
	.steps button.on {
		background: var(--gold);
		box-shadow: 0 0 0 4px var(--gold-soft);
	}
	.steps button.after {
		opacity: 0.55;
	}
	.lbl {
		position: absolute;
		left: 50%;
		bottom: -18px;
		transform: translateX(-50%);
		font-size: 0.64rem;
		color: var(--muted);
		white-space: nowrap;
	}
	.help {
		font-size: 0.8rem;
		color: var(--muted);
		line-height: 1.4;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.grow {
		flex: 1;
	}
	.toggle {
		position: relative;
		width: 48px;
		height: 28px;
		flex: none;
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line-strong);
	}
	.toggle::after {
		content: '';
		position: absolute;
		top: 3px;
		left: 3px;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: var(--fg-2);
		transition:
			transform 0.18s ease,
			background 0.18s ease;
	}
	.toggle[aria-checked='true'] {
		background: var(--gold);
		border-color: transparent;
	}
	.toggle[aria-checked='true']::after {
		transform: translateX(20px);
		background: var(--gold-ink);
	}
	.options {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.opt {
		appearance: none;
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--fg-2);
		font-size: 0.8rem;
		font-weight: 500;
		padding: 6px 12px;
		border-radius: var(--r-pill);
		min-height: 34px;
	}
	.opt.on {
		background: var(--gold);
		color: var(--gold-ink);
		border-color: transparent;
	}
	.value {
		appearance: none;
		text-align: left;
		border: 1px dashed var(--line-strong);
		background: transparent;
		color: var(--fg);
		padding: 10px 12px;
		border-radius: var(--r-s);
		min-height: 42px;
		font-size: 0.92rem;
	}
</style>
