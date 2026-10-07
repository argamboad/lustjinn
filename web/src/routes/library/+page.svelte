<script lang="ts">
	import { onMount } from 'svelte';
	import AppBar from '#lib/AppBar.svelte';
	import Tabs from '#lib/Tabs.svelte';
	import { api, type Defaults, type Entry, type Shelf } from '#lib/api.ts';
	import { toasts } from '#lib/toasts.svelte.ts';

	const shelves: { id: Shelf; label: string; one: string }[] = [
		{ id: 'characters', label: 'Characters', one: 'character' },
		{ id: 'personas', label: 'Personas', one: 'persona' },
		{ id: 'snippets', label: 'Snippets', one: 'snippet' }
	];

	let shelf = $state<Shelf>('characters');
	let hidden = $state(false);
	let entries = $state<Entry[] | null>(null);
	let defaults = $state<Defaults | null>(null);

	const current = $derived(shelves.find((s) => s.id === shelf)!);

	onMount(() => {
		try {
			const saved = localStorage.getItem('lustjinn-shelf');
			if (saved === 'personas' || saved === 'snippets') shelf = saved;
		} catch {
			/* a convenience only */
		}
		void load();
		api
			.defaults()
			.then((d) => (defaults = d))
			.catch(() => undefined);
	});

	async function load() {
		entries = null;
		try {
			entries = await api.entries(shelf, hidden);
		} catch (error) {
			toasts.show(
				'danger',
				'Could not read the shelf',
				error instanceof Error ? error.message : undefined
			);
			entries = [];
		}
	}

	function pick(next: Shelf) {
		shelf = next;
		try {
			localStorage.setItem('lustjinn-shelf', next);
		} catch {
			/* a convenience only */
		}
		void load();
	}

	async function makeDefault(entry: Entry) {
		try {
			defaults = await api.setDefaults(entry.id);
			toasts.show(
				'ok',
				`${entry.name} is the default persona`,
				'Every story that names none plays as them.'
			);
		} catch (error) {
			toasts.show('danger', 'Not set', error instanceof Error ? error.message : undefined);
		}
	}

	function initial(entry: Entry): string {
		return entry.name.replace(/^_/, '').charAt(0).toUpperCase() || '?';
	}
</script>

<div class="screen">
	<AppBar title="Library" mark>
		{#snippet actions()}
			<a class="btn primary small" href="/library/{shelf}/new">New {current.one}</a>
		{/snippet}
	</AppBar>
	<div class="toolbar">
		<div class="seg" role="tablist" aria-label="Shelf">
			{#each shelves as s (s.id)}
				<button type="button" role="tab" aria-selected={shelf === s.id} onclick={() => pick(s.id)}
					>{s.label}</button
				>
			{/each}
		</div>
		<label class="hidden-toggle">
			<input type="checkbox" bind:checked={hidden} onchange={load} />
			<span>Show hidden</span>
		</label>
	</div>
	<main class="list">
		{#if entries === null}
			<p class="muted center">Reading the shelf…</p>
		{:else if entries.length === 0}
			<div class="empty">
				<p class="muted">
					{#if shelf === 'snippets'}
						No snippets yet. A snippet is text you insert often — typed as <code>:name</code> in the composer,
						or picked from its list.
					{:else if shelf === 'personas'}
						No personas yet. A persona is who you are in a story; the default one plays in every
						story that names none.
					{:else}
						No characters yet. A character is a card — who they are, how they speak, where the scene
						opens.
					{/if}
				</p>
				<a class="btn primary" href="/library/{shelf}/new">Write the first {current.one}</a>
			</div>
		{:else}
			{#each entries as entry (entry.id)}
				<a class="entry" href="/library/{shelf}/{entry.id}">
					<span class="who">{initial(entry)}</span>
					<span class="text">
						<span class="name">
							{entry.name}
							{#if entry.hidden}<span class="chip">hidden</span>{/if}
							{#if shelf === 'personas' && defaults?.default_persona_id === entry.id}
								<span class="chip gold">default</span>
							{/if}
						</span>
						<span class="preview prose">{entry.preview}</span>
						<span class="meta"
							>v{entry.version} · {new Date(entry.updated_at).toLocaleDateString()}</span
						>
					</span>
					{#if shelf === 'personas' && defaults?.default_persona_id !== entry.id}
						<button
							type="button"
							class="link"
							onclick={(e) => {
								e.preventDefault();
								makeDefault(entry);
							}}>Make default</button
						>
					{/if}
				</a>
			{/each}
		{/if}
	</main>
	<Tabs />
</div>

<style>
	.screen {
		height: 100%;
		display: flex;
		flex-direction: column;
	}
	.btn.small {
		min-height: 36px;
		padding: 6px 14px;
		font-size: 0.85rem;
		text-decoration: none;
		box-shadow: none;
	}
	.toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px 6px;
	}
	.seg {
		display: inline-flex;
		padding: 3px;
		gap: 2px;
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.seg button {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--fg-2);
		font-size: 0.85rem;
		font-weight: 500;
		padding: 6px 12px;
		min-height: 34px;
		border-radius: var(--r-pill);
	}
	.seg button[aria-selected='true'] {
		background: var(--gold);
		color: var(--gold-ink);
	}
	.hidden-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.82rem;
		color: var(--muted);
	}
	.hidden-toggle input {
		accent-color: var(--gold);
		width: 18px;
		height: 18px;
	}
	.list {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding: 4px 12px 24px;
		display: grid;
		gap: 8px;
		align-content: start;
	}
	.center {
		text-align: center;
		padding: 32px 0;
	}
	.empty {
		display: grid;
		gap: 14px;
		justify-items: center;
		padding: 40px 16px;
		text-align: center;
	}
	.empty p {
		max-width: 46ch;
	}
	.entry {
		display: grid;
		grid-template-columns: 44px 1fr auto;
		gap: 12px;
		align-items: center;
		padding: 12px;
		border-radius: var(--r-m);
		background: var(--surface);
		border: 1px solid var(--line);
		text-decoration: none;
		color: inherit;
	}
	.who {
		width: 44px;
		height: 44px;
		border-radius: 12px;
		background: var(--surface-2);
		display: grid;
		place-items: center;
		font-family: var(--font-prose);
		font-size: 1.25rem;
		color: var(--gold-text);
	}
	.text {
		min-width: 0;
		display: grid;
		gap: 2px;
	}
	.name {
		font-weight: 600;
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
	}
	.preview {
		color: var(--fg-2);
		font-size: 0.88rem;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.meta {
		font-size: 0.72rem;
		color: var(--muted);
	}
	.link {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--gold-text);
		font-weight: 600;
		font-size: 0.78rem;
		padding: 8px;
		min-height: 36px;
	}
	@media (min-width: 900px) {
		.screen {
			max-width: 760px;
			margin: 0 auto;
		}
	}
</style>
