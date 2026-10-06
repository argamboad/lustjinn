<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import AppBar from '#lib/AppBar.svelte';
	import Tabs from '#lib/Tabs.svelte';
	import { api, ApiError, type Story } from '#lib/api.ts';
	import { stories } from '#lib/stories.svelte.ts';
	import { toasts } from '#lib/toasts.svelte.ts';

	let query = $state('');
	let monthCost = $state<string | null>(null);
	let open = $state<string | null>(null); // the card whose actions are showing
	let confirming = $state<string | null>(null); // the card asked to confirm a delete
	let pulling = $state(0); // pull-to-refresh distance

	const shown = $derived.by(() => {
		const list = stories.list ?? [];
		const q = query.trim().toLowerCase();
		if (!q) return list;
		return list.filter(
			(s) =>
				s.name.toLowerCase().includes(q) ||
				s.character_name.toLowerCase().includes(q) ||
				(s.last_message_preview ?? '').toLowerCase().includes(q)
		);
	});

	const sub = $derived.by(() => {
		const n = stories.list?.length;
		const count = n === undefined ? '' : n === 1 ? '1 story' : `${n} stories`;
		return monthCost ? `${count} · ${monthCost} this month` : count;
	});

	onMount(() => {
		void stories.refresh();
		void loadMonth();
	});

	async function loadMonth() {
		const now = new Date();
		const first = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString();
		try {
			const report = await api.spend(first);
			monthCost = money(report.cost);
		} catch {
			monthCost = null; // the header can do without it
		}
	}

	function money(cost: string): string {
		const n = Number(cost);
		return n < 0.01 && n > 0 ? '<$0.01' : `$${n.toFixed(2)}`;
	}

	function initial(story: Story): string {
		return story.character_name.trim().charAt(0).toUpperCase() || '?';
	}

	function when(story: Story): string {
		const at = new Date(story.last_message_at ?? story.created_at);
		const diff = Date.now() - at.getTime();
		const minutes = Math.round(diff / 60000);
		if (minutes < 1) return 'now';
		if (minutes < 60) return `${minutes}m`;
		const hours = Math.round(minutes / 60);
		if (hours < 24) return `${hours}h`;
		const days = Math.round(hours / 24);
		if (days === 1) return 'yesterday';
		if (days < 7) return at.toLocaleDateString(undefined, { weekday: 'short' });
		return at.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	function shortModel(model: string | null): string | null {
		if (!model) return null;
		return model.split('/').pop()?.replace(/-/g, ' ') ?? model;
	}

	// --- swipe: a card dragged left shows Branch and Delete -------------------------------
	let drag = $state<{ id: string; x: number; dx: number } | null>(null);

	function pointerdown(event: PointerEvent, id: string) {
		if (event.pointerType === 'mouse' && event.button !== 0) return;
		drag = { id, x: event.clientX, dx: 0 };
	}
	function pointermove(event: PointerEvent) {
		if (!drag) return;
		drag.dx = event.clientX - drag.x;
	}
	function pointerup(event: PointerEvent, id: string) {
		if (!drag || drag.id !== id) return;
		const dx = event.clientX - drag.x;
		if (dx < -50) open = id;
		else if (dx > 30) open = null;
		else if (Math.abs(dx) < 8 && open === id) open = null;
		drag = null;
	}
	function offset(id: string): string {
		if (drag && drag.id === id && drag.dx < 0) return `${Math.max(drag.dx, -140)}px`;
		return open === id ? '-140px' : '0px';
	}

	async function branch(story: Story) {
		try {
			const full = await api.story(story.id);
			const last = full.messages.at(-1);
			if (!last) {
				toasts.show('info', 'Nothing to branch yet', 'The story has no turns.');
				return;
			}
			const copy = await api.branch(story.id, last.id);
			stories.touch(copy);
			open = null;
			toasts.show('ok', `Branched as “${copy.name}”`, 'The original is untouched.');
			await goto(`/story/${copy.id}`);
		} catch (error) {
			toasts.show('danger', 'Could not branch', error instanceof Error ? error.message : undefined);
		}
	}

	async function remove(story: Story) {
		try {
			await api.deleteStory(story.id);
			stories.remove(story.id);
			toasts.show('ok', `Deleted “${story.name}”`, 'Its rows stay until you purge it.');
		} catch (error) {
			toasts.show(
				'danger',
				'Could not delete',
				error instanceof ApiError ? error.message : undefined
			);
		} finally {
			confirming = null;
			open = null;
		}
	}

	// --- pull to refresh -------------------------------------------------------------------
	let pullStart: number | null = null;
	let scroller: HTMLElement | undefined = $state();

	function touchstart(event: TouchEvent) {
		if ((scroller?.scrollTop ?? 1) <= 0) pullStart = event.touches[0].clientY;
	}
	function touchmove(event: TouchEvent) {
		if (pullStart === null) return;
		pulling = Math.max(0, Math.min(90, (event.touches[0].clientY - pullStart) / 2));
	}
	async function touchend() {
		if (pulling > 60) await stories.refresh();
		pulling = 0;
		pullStart = null;
	}
</script>

<div class="screen">
	<AppBar title="Stories" {sub} mark>
		{#snippet actions()}
			<a class="bar-link" href="/library">Library</a>
			<a class="avatar" href="/you" aria-label="You">R</a>
		{/snippet}
	</AppBar>
	<div class="search">
		<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
			><path
				d="M10 2a8 8 0 1 0 4.9 14.3l5.4 5.4 1.4-1.4-5.4-5.4A8 8 0 0 0 10 2zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z"
				fill="currentColor"
			/></svg
		>
		<input
			id="story-search"
			type="search"
			placeholder="Search your stories"
			bind:value={query}
			autocomplete="off"
		/>
	</div>
	<main
		class="list"
		bind:this={scroller}
		ontouchstart={touchstart}
		ontouchmove={touchmove}
		ontouchend={touchend}
	>
		{#if pulling > 0}
			<div class="pull" style:height="{pulling}px" aria-hidden="true">
				<span class:ready={pulling > 60}
					>{pulling > 60 ? 'Let go to refresh' : 'Pull to refresh'}</span
				>
			</div>
		{/if}
		{#if stories.problem}
			<p class="problem">
				{stories.problem}
				<button class="btn ghost" type="button" onclick={() => stories.refresh()}>Try again</button>
			</p>
		{:else if stories.list === null}
			<p class="muted center">Reading your stories…</p>
		{:else if shown.length === 0}
			<div class="empty">
				{#if query}
					<p class="muted">Nothing matches “{query}”.</p>
				{:else}
					<p class="muted">No stories yet.</p>
					<a class="btn primary" href="/new">Start one</a>
				{/if}
			</div>
		{:else}
			{#each shown as story (story.id)}
				<div class="row">
					<div class="actions" aria-hidden={open !== story.id}>
						<button
							type="button"
							class="act branch"
							onclick={() => branch(story)}
							tabindex={open === story.id ? 0 : -1}>Branch</button
						>
						<button
							type="button"
							class="act delete"
							onclick={() => (confirming = story.id)}
							tabindex={open === story.id ? 0 : -1}>Delete</button
						>
					</div>
					<a
						class="story"
						href="/story/{story.id}"
						style:transform="translateX({offset(story.id)})"
						onpointerdown={(e) => pointerdown(e, story.id)}
						onpointermove={pointermove}
						onpointerup={(e) => pointerup(e, story.id)}
						onpointercancel={() => (drag = null)}
						onclick={(e) => {
							if (open === story.id || (drag && Math.abs(drag.dx) > 8)) e.preventDefault();
						}}
						draggable="false"
					>
						<div class="who">{initial(story)}</div>
						<div class="text">
							<div class="name">
								<span>{story.name}</span>
								{#if story.model}<span class="chip gold small">{shortModel(story.model)}</span>{/if}
							</div>
							<div class="preview prose">
								{story.last_message_preview ?? `With ${story.character_name}. Nothing said yet.`}
							</div>
						</div>
						<div class="when">{when(story)}</div>
					</a>
					{#if confirming === story.id}
						<div class="confirm" role="alertdialog" aria-label="Delete this story?">
							<span>Delete “{story.name}”? It is hidden, not erased.</span>
							<button type="button" class="btn ghost" onclick={() => (confirming = null)}
								>Keep</button
							>
							<button type="button" class="btn danger" onclick={() => remove(story)}>Delete</button>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</main>
	<a class="fab" href="/new" aria-label="New story">+</a>
	<Tabs />
</div>

<style>
	.screen {
		height: 100%;
		display: flex;
		flex-direction: column;
	}
	.bar-link {
		display: none;
		text-decoration: none;
		color: var(--fg-2);
		font-weight: 500;
		font-size: 0.9rem;
		padding: 6px 10px;
	}
	@media (min-width: 900px) {
		.bar-link {
			display: inline-block;
		}
	}
	.avatar {
		width: 34px;
		height: 34px;
		border-radius: 50%;
		background: var(--gold-soft);
		color: var(--gold-text);
		display: grid;
		place-items: center;
		font-weight: 600;
		font-size: 0.85rem;
		text-decoration: none;
	}
	.search {
		margin: 10px 14px 8px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
		color: var(--muted);
	}
	.search:focus-within {
		border-color: var(--gold);
	}
	.search input {
		flex: 1;
		background: transparent;
		border: 0;
		outline: none;
		color: var(--fg);
		min-height: 42px;
		font-size: 0.95rem;
	}
	.list {
		flex: 1;
		overflow: auto;
		padding: 0 12px 96px;
		display: grid;
		gap: 8px;
		align-content: start;
		overscroll-behavior: contain;
	}
	.pull {
		display: grid;
		place-items: center;
		color: var(--muted);
		font-size: 0.75rem;
		overflow: hidden;
	}
	.pull .ready {
		color: var(--gold-text);
	}
	.row {
		position: relative;
		border-radius: var(--r-m);
		overflow: hidden;
	}
	.actions {
		position: absolute;
		inset: 0 0 0 auto;
		width: 140px;
		display: flex;
	}
	.act {
		flex: 1;
		border: 0;
		font-weight: 600;
		font-size: 0.8rem;
		color: #fff;
	}
	.act.branch {
		background: var(--gold-2);
		color: var(--gold-ink);
	}
	.act.delete {
		background: var(--danger);
	}
	.story {
		position: relative;
		display: grid;
		grid-template-columns: 44px 1fr auto;
		gap: 12px;
		padding: 12px;
		border-radius: var(--r-m);
		background: var(--surface);
		border: 1px solid var(--line);
		text-decoration: none;
		color: inherit;
		transition: transform 0.18s ease;
		touch-action: pan-y;
		user-select: none;
	}
	.story:active {
		background: var(--surface-2);
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
		min-width: 0;
	}
	.name > span:first-child {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.chip.small {
		padding: 1px 7px;
		font-size: 0.66rem;
	}
	.preview {
		color: var(--fg-2);
		font-size: 0.88rem;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		line-height: 1.4;
	}
	.when {
		font-size: 0.72rem;
		color: var(--muted);
		padding-top: 2px;
	}
	.confirm {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		padding: 10px 12px;
		background: var(--surface-2);
		border-top: 1px solid var(--line);
		font-size: 0.88rem;
		color: var(--fg-2);
	}
	.confirm span {
		flex: 1 1 100%;
	}
	.btn.danger {
		background: var(--danger);
		color: #fff;
	}
	.problem {
		display: grid;
		gap: 10px;
		justify-items: start;
		color: var(--danger);
		padding: 16px 4px;
	}
	.center {
		text-align: center;
		padding: 32px 0;
	}
	.empty {
		display: grid;
		gap: 14px;
		justify-items: center;
		padding: 48px 16px;
		text-align: center;
	}
	.fab {
		position: fixed;
		right: 18px;
		bottom: calc(78px + var(--safe-bottom));
		width: 56px;
		height: 56px;
		border-radius: 18px;
		background: var(--gold);
		color: var(--gold-ink);
		display: grid;
		place-items: center;
		font-size: 1.8rem;
		font-weight: 500;
		text-decoration: none;
		box-shadow: 0 10px 30px var(--gold-glow);
		z-index: 5;
	}
	@media (min-width: 900px) {
		.screen {
			max-width: 760px;
			margin: 0 auto;
		}
		.fab {
			bottom: 26px;
			right: calc(50% - 380px + 18px);
		}
	}
</style>
