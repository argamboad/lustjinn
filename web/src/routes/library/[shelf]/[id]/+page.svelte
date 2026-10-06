<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AppBar from '#lib/AppBar.svelte';
	import Sheet from '#lib/Sheet.svelte';
	import { api, ApiError, type EntryFull, type HistoryEntry, type Shelf } from '#lib/api.ts';
	import { toasts } from '#lib/toasts.svelte.ts';

	const shelf = $derived(page.params.shelf as Shelf);
	const id = $derived(page.params.id ?? 'new');
	const creating = $derived(id === 'new');
	const one = $derived(
		shelf === 'characters' ? 'character' : shelf === 'personas' ? 'persona' : 'snippet'
	);

	let entry = $state<EntryFull | null>(null);
	let name = $state('');
	let text = $state('');
	let opening = $state('');
	let version = $state(0);
	let loaded = $state(false);
	let busy = $state(false);
	/** The entry as the server has it, when a save found it changed elsewhere. */
	let theirs = $state<EntryFull | null>(null);
	let history = $state<HistoryEntry[] | null>(null);
	let historyOpen = $state(false);
	let deleting = $state(false);

	const dirty = $derived(
		creating
			? name.trim().length > 0 || text.trim().length > 0
			: entry !== null &&
					(name !== entry.name || text !== entry.text || opening !== (entry.opening ?? ''))
	);
	const ready = $derived(name.trim().length > 0 && text.trim().length > 0 && !busy);

	onMount(async () => {
		if (creating) {
			loaded = true;
			return;
		}
		try {
			take(await api.entry(shelf, id));
		} catch (error) {
			toasts.show(
				'danger',
				`Could not open the ${one}`,
				error instanceof Error ? error.message : undefined
			);
		} finally {
			loaded = true;
		}
	});

	function take(found: EntryFull) {
		entry = found;
		name = found.name;
		text = found.text;
		opening = found.opening ?? '';
		version = found.version;
		theirs = null;
	}

	async function save() {
		if (!ready) return;
		busy = true;
		try {
			if (creating) {
				const made = await api.createEntry(shelf, {
					name: name.trim(),
					text,
					opening: shelf === 'characters' ? opening.trim() || null : undefined
				});
				toasts.show('ok', `${made.name} is on the shelf`);
				await goto(`/library/${shelf}/${made.id}`, { replaceState: true });
				take(made);
			} else {
				const saved = await api.saveEntry(shelf, id, {
					version,
					name: name.trim(),
					text,
					...(shelf === 'characters' ? { opening: opening.trim() || null } : {})
				});
				take(saved);
				toasts.show(
					'ok',
					'Saved',
					`Version ${saved.version}. Every story using it reads the new text from its next turn.`
				);
			}
		} catch (error) {
			if (error instanceof ApiError && error.status === 409 && isConflict(error.body)) {
				theirs = error.body.current;
				version = theirs.version; // saving again replaces what is there now
			} else {
				toasts.show(
					'danger',
					'Not saved',
					error instanceof Error ? error.message : undefined,
					8000
				);
			}
		} finally {
			busy = false;
		}
	}

	function isConflict(body: unknown): body is { message: string; current: EntryFull } {
		return typeof body === 'object' && body !== null && 'current' in body;
	}

	function takeTheirs() {
		if (theirs) take(theirs);
	}

	async function showHistory() {
		historyOpen = true;
		if (history === null) {
			try {
				history = await api.history(shelf, id);
			} catch {
				history = [];
			}
		}
	}

	function restore(h: HistoryEntry) {
		name = h.name;
		text = h.text;
		opening = h.opening ?? '';
		historyOpen = false;
		toasts.show(
			'info',
			`Version ${h.version} is in the editor`,
			'Save to make it the current one.'
		);
	}

	async function remove() {
		busy = true;
		try {
			await api.deleteEntry(shelf, id);
			toasts.show('ok', `Deleted ${entry?.name ?? 'the ' + one}`);
			await goto('/library');
		} catch (error) {
			toasts.show(
				'danger',
				'Not deleted',
				error instanceof Error ? error.message : undefined,
				10000
			);
		} finally {
			busy = false;
			deleting = false;
		}
	}
</script>

<div class="screen">
	<AppBar
		title={creating ? `New ${one}` : (entry?.name ?? one)}
		sub={entry
			? `version ${entry.version}${entry.used_by.length ? ` · used by ${entry.used_by.join(', ')}` : ''}`
			: undefined}
		back="/library"
	>
		{#snippet actions()}
			{#if !creating && entry}
				<button class="btn icon" type="button" aria-label="History" onclick={showHistory}>⌛</button
				>
			{/if}
		{/snippet}
	</AppBar>

	<main>
		{#if !loaded}
			<p class="muted center">Opening…</p>
		{:else if !creating && !entry}
			<p class="muted center">There is no {one} with that id.</p>
		{:else}
			{#if theirs}
				<div class="conflict" role="alert">
					<b>This {one} changed somewhere else since you opened it.</b>
					<p class="muted">Nothing was saved. Their text is below; yours is in the editor.</p>
					<pre class="prose">{theirs.text}</pre>
					<div class="row">
						<button type="button" class="btn primary" onclick={save}>Replace it with mine</button>
						<button type="button" class="btn ghost" onclick={takeTheirs}>Take theirs</button>
					</div>
				</div>
			{/if}
			<label class="field">
				<span>Name</span>
				<input
					class="input"
					id="entry-name"
					type="text"
					bind:value={name}
					maxlength="200"
					placeholder={shelf === 'snippets' ? 'storm (typed as :storm)' : 'A name'}
				/>
			</label>
			<label class="field grow">
				<span
					>{shelf === 'characters'
						? 'The card'
						: shelf === 'personas'
							? 'Who you are'
							: 'The text'}</span
				>
				<textarea
					class="input prose"
					id="entry-text"
					bind:value={text}
					rows={shelf === 'snippets' ? 4 : 14}
					placeholder={shelf === 'characters'
						? 'Who they are, how they speak, the world they live in…'
						: ''}></textarea>
			</label>
			{#if shelf === 'characters'}
				<label class="field">
					<span>Opening <small class="muted">— the scene a story starts on, optional</small></span>
					<textarea class="input prose" id="entry-opening" bind:value={opening} rows="5"></textarea>
				</label>
			{/if}
			<div class="foot">
				<button
					type="button"
					class="btn primary"
					onclick={save}
					disabled={!ready || (!creating && !dirty && !theirs)}
				>
					{busy ? 'Saving…' : creating ? `Add the ${one}` : 'Save'}
				</button>
				{#if !creating}
					{#if deleting}
						<span class="muted small">Delete {entry?.name}?</span>
						<button type="button" class="btn danger" onclick={remove} disabled={busy}>Delete</button
						>
						<button type="button" class="btn ghost" onclick={() => (deleting = false)}>Keep</button>
					{:else}
						<button type="button" class="btn ghost" onclick={() => (deleting = true)}>Delete</button
						>
					{/if}
				{/if}
			</div>
			{#if entry?.used_by.length}
				<p class="muted small">
					Used by {entry.used_by.join(', ')}: a save reaches them from their next turn, and it
					cannot be deleted while they do.
				</p>
			{/if}
		{/if}
	</main>
</div>

<Sheet bind:open={historyOpen} title="Every saved version" hint="newest first">
	{#if history === null}
		<p class="muted">Reading…</p>
	{:else if history.length === 0}
		<p class="muted">Nothing yet.</p>
	{:else}
		<div class="versions">
			{#each history as h (h.version)}
				<div class="version">
					<div class="vhead">
						<b>v{h.version}</b>
						<span class="muted small">{new Date(h.saved_at).toLocaleString()}</span>
						{#if h.version !== entry?.version}
							<button type="button" class="link" onclick={() => restore(h)}
								>Put in the editor</button
							>
						{:else}
							<span class="chip gold">current</span>
						{/if}
					</div>
					<p class="prose vtext">{h.text.slice(0, 240)}{h.text.length > 240 ? '…' : ''}</p>
				</div>
			{/each}
		</div>
	{/if}
</Sheet>

<style>
	.screen {
		min-height: 100%;
		display: flex;
		flex-direction: column;
	}
	main {
		flex: 1;
		display: grid;
		gap: 14px;
		align-content: start;
		padding: 14px 16px calc(24px + var(--safe-bottom));
		max-width: 760px;
		width: 100%;
		margin: 0 auto;
	}
	.center {
		text-align: center;
		padding: 32px;
	}
	textarea.input {
		resize: vertical;
		line-height: 1.55;
		font-size: 1rem;
	}
	.foot {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
	}
	.btn.danger {
		background: var(--danger);
		color: #fff;
	}
	.small {
		font-size: 0.82rem;
	}
	.conflict {
		display: grid;
		gap: 10px;
		padding: 14px;
		border-radius: var(--r-m);
		border: 1px solid var(--warn);
		background: var(--surface);
	}
	.conflict pre {
		white-space: pre-wrap;
		margin: 0;
		max-height: 240px;
		overflow: auto;
		padding: 10px 12px;
		border-radius: var(--r-s);
		background: var(--surface-2);
		font-size: 0.9rem;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.versions {
		display: grid;
		gap: 10px;
	}
	.version {
		display: grid;
		gap: 6px;
		padding: 10px 12px;
		border-radius: var(--r-s);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.vhead {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
	}
	.vhead b {
		font-weight: 600;
	}
	.vtext {
		font-size: 0.88rem;
		color: var(--fg-2);
		white-space: pre-wrap;
	}
	.link {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--gold-text);
		font-weight: 600;
		font-size: 0.78rem;
		padding: 6px 8px;
		margin-left: auto;
		min-height: 32px;
	}
</style>
