<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import AppBar from '#lib/AppBar.svelte';
	import Composer from '#lib/Composer.svelte';
	import MessageView from '#lib/MessageView.svelte';
	import MeterStrip from '#lib/MeterStrip.svelte';
	import RerollSheet from '#lib/RerollSheet.svelte';
	import Sheet from '#lib/Sheet.svelte';
	import StoryRail from '#lib/StoryRail.svelte';
	import {
		api,
		ApiError,
		Unreachable,
		type Command,
		type Done,
		type EntryFull,
		type Message,
		type StoryWithMessages
	} from '#lib/api.ts';
	import { Extras } from '#lib/extras.svelte.ts';
	import { expandEmoji } from '#lib/shortcodes.ts';
	import { stories } from '#lib/stories.svelte.ts';
	import { toasts } from '#lib/toasts.svelte.ts';

	const id = $derived(page.params.id ?? '');

	let story = $state<StoryWithMessages | null>(null);
	let problem = $state<string | null>(null);
	let commands = $state<Command[]>([]);
	let snippets = $state<EntryFull[]>([]);
	/** The reader's message as sent, before the API confirms it. */
	let pendingSent = $state<string | null>(null);
	/** The reply as it streams in. */
	let pendingReply = $state<string | null>(null);
	/** The newest reply, hidden while a reroll writes its replacement. */
	let replacing = $state<string | null>(null);
	/** Answers shown once and kept nowhere: `/ask`, `/recap`, a `/tracker` set. */
	let notes = $state<{ id: number; title: string; text: string }[]>([]);
	let rerollOpen = $state(false);
	let menuFor = $state<Message | null>(null);
	let storyMenu = $state(false);
	let extras = $state<Extras | null>(null);
	let railOpen = $state(false);
	let railSection = $state<'dials' | 'meters' | 'prompt'>('dials');
	let renaming = $state(false);
	let newName = $state('');
	let cutConfirm = $state(false);
	let composer: Composer | undefined = $state();
	let scroller: HTMLElement | undefined = $state();
	let warnedFallback = false;
	let noteId = 1;

	const busy = $derived(pendingReply !== null);
	const visible = $derived((story?.messages ?? []).filter((m) => m.id !== replacing));
	const newestReply = $derived.by(() => {
		const last = visible.at(-1);
		return last && last.role === 'assistant' ? last : null;
	});
	const turns = $derived(visible.filter((m) => m.role === 'user').length);
	const sub = $derived.by(() => {
		if (!story) return '';
		const parts = [story.character_name, story.persona_name ?? 'no persona', `turn ${turns}`];
		if (story.model) parts.push(story.model.split('/').pop() ?? story.model);
		return parts.join(' · ');
	});

	onMount(async () => {
		try {
			[story, commands] = await Promise.all([api.story(id), api.commands()]);
			api
				.snippets()
				.then((found) => (snippets = found))
				.catch(() => undefined);
			extras = new Extras(id);
			void extras.load();
			await scrollToEnd(false);
		} catch (error) {
			problem = error instanceof Error ? error.message : 'The story could not be read.';
		}
	});

	async function scrollToEnd(smooth = true) {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
	}

	function touchStoryList() {
		if (!story) return;
		const last = story.messages.at(-1);
		stories.touch({
			...story,
			last_message_at: last?.sent_at ?? story.last_message_at,
			last_message_preview: last?.text.slice(0, 200) ?? story.last_message_preview
		});
	}

	function note(title: string, text: string) {
		notes = [...notes, { id: noteId++, title, text }];
		void scrollToEnd();
	}

	/** Runs one streamed call and folds what it ends with into the story. */
	async function run(call: (onDelta: (t: string) => void) => Promise<Done>) {
		if (!story) return;
		pendingReply = '';
		try {
			const done = await call((piece) => {
				pendingReply = (pendingReply ?? '') + piece;
				void scrollToEnd();
			});
			finish(done);
		} catch (error) {
			if (error instanceof ApiError) toasts.show('danger', 'Refused', error.message, 8000);
			else if (error instanceof Unreachable)
				toasts.show('danger', 'Lost the server', error.message);
			else toasts.show('danger', 'Something went wrong');
			await reload();
		} finally {
			pendingReply = null;
			pendingSent = null;
			replacing = null;
		}
	}

	function finish(done: Done) {
		if (!story) return;
		switch (done.kind) {
			case 'turn': {
				const kept = story.messages.filter((m) => m.id !== replacing);
				const added = [done.sent, done.reply].filter((m): m is Message => m !== null);
				story.messages = [...kept, ...added.filter((a) => !kept.some((k) => k.id === a.id))];
				if (done.replayed)
					toasts.show(
						'info',
						'Already answered',
						'That message had been sent before; here is its reply.'
					);
				if (done.reply.fell_back_from && !warnedFallback) {
					warnedFallback = true;
					toasts.show(
						'warn',
						'Written by the default model',
						`${done.reply.fell_back_from} could not take this turn. The story keeps its model for the next one.`,
						10000
					);
				}
				touchStoryList();
				void extras?.refresh(); // the meters may have moved; the audit has a new line
				break;
			}
			case 'aside':
				note(`You asked: ${done.aside.question}`, done.aside.answer);
				break;
			case 'said':
				note('', done.text);
				break;
			case 'error':
				toasts.show('danger', 'The model did not answer', done.detail, 10000);
				if (done.sent && !story.messages.some((m) => m.id === done.sent?.id)) {
					story.messages = [...story.messages, done.sent];
				}
				break;
		}
		void scrollToEnd();
	}

	async function reload() {
		try {
			story = await api.story(id);
		} catch {
			/* the next action reloads again */
		}
	}

	function send(typed: string) {
		// Emoji shortcodes expand here; a bare `:name` is a snippet trigger the API expands.
		const text = expandEmoji(typed);
		pendingSent = text;
		void scrollToEnd();
		void run((onDelta) => api.send(id, text, onDelta));
	}

	function carryOn() {
		void run((onDelta) => api.carryOn(id, onDelta));
	}

	function reroll(reason: string, instructions: string | null) {
		if (!newestReply) return;
		replacing = newestReply.id;
		void run((onDelta) => api.reroll(id, onDelta, { reason, instructions }));
	}

	async function branchFrom(message: Message) {
		if (!story) return;
		menuFor = null;
		try {
			const copy = await api.branch(id, message.id);
			stories.touch(copy);
			toasts.show(
				'ok',
				`Branched as “${copy.name}”`,
				`From turn ${message.sequence}. The original is untouched.`
			);
			await goto(`/story/${copy.id}`);
			story = copy;
			await scrollToEnd(false);
		} catch (error) {
			toasts.show('danger', 'Could not branch', error instanceof Error ? error.message : undefined);
		}
	}

	async function cutFrom(message: Message) {
		if (!story) return;
		try {
			const result = await api.deleteFrom(id, message.id);
			story = result.story;
			toasts.show(
				'ok',
				`Cut ${result.hidden} ${result.hidden === 1 ? 'turn' : 'turns'}`,
				'They are hidden, and the memory of them went with them.'
			);
			touchStoryList();
		} catch (error) {
			toasts.show('danger', 'Could not cut', error instanceof Error ? error.message : undefined);
		} finally {
			menuFor = null;
			cutConfirm = false;
		}
	}

	async function copyText(message: Message) {
		menuFor = null;
		try {
			await navigator.clipboard.writeText(message.text);
			toasts.show('ok', 'Copied');
		} catch {
			toasts.show('info', 'Select the text to copy it');
		}
	}

	async function rename() {
		if (!story || !newName.trim()) return;
		try {
			const renamed = await api.renameStory(id, newName.trim());
			story.name = renamed.name;
			stories.touch({ ...story, ...renamed });
			renaming = false;
			storyMenu = false;
		} catch (error) {
			toasts.show('danger', 'Could not rename', error instanceof Error ? error.message : undefined);
		}
	}

	async function deleteStory() {
		if (!story) return;
		try {
			await api.deleteStory(id);
			stories.remove(id);
			toasts.show('ok', `Deleted “${story.name}”`);
			await goto('/');
		} catch (error) {
			toasts.show('danger', 'Could not delete', error instanceof Error ? error.message : undefined);
		}
	}

	const cutCount = $derived(
		menuFor && story ? visible.filter((m) => m.sequence >= menuFor!.sequence).length : 0
	);
</script>

<div class="screen">
	<AppBar title={story?.name ?? 'Story'} {sub} back="/">
		{#snippet actions()}
			<button
				class="btn icon rail-button"
				type="button"
				aria-label="Dials and meters"
				onclick={() => (railOpen = true)}>◐</button
			>
			<button
				class="btn icon"
				type="button"
				aria-label="Story menu"
				onclick={() => (storyMenu = true)}>⋯</button
			>
		{/snippet}
	</AppBar>

	<div class="body">
		<div class="column">
			<main class="convo" bind:this={scroller}>
				{#if problem}
					<p class="problem">{problem}</p>
				{:else if !story}
					<p class="muted center">Opening the story…</p>
				{:else}
					{#if story.messages.length === 0 && !pendingSent}
						<p class="muted center">
							Nothing has been said yet. Write the first turn, or carry on to let {story.character_name}
							begin.
						</p>
					{/if}
					{#each visible as message (message.id)}
						<MessageView
							{message}
							newest={newestReply?.id === message.id && !busy}
							onreroll={() => (rerollOpen = true)}
							onmenu={() => (menuFor = message)}
						/>
					{/each}
					{#each notes as n (n.id)}
						<aside class="note">
							{#if n.title}<b>{n.title}</b>{/if}
							<p class="prose">{n.text}</p>
							<footer>
								<span class="muted">shown once, not stored</span>
								<button
									type="button"
									class="link"
									onclick={() => (notes = notes.filter((x) => x.id !== n.id))}>Dismiss</button
								>
							</footer>
						</aside>
					{/each}
					{#if pendingSent !== null}
						<MessageView message={{ role: 'user', text: pendingSent }} />
					{/if}
					{#if pendingReply !== null}
						<MessageView message={{ role: 'assistant', text: pendingReply }} streaming />
					{/if}
				{/if}
			</main>

			{#if extras}
				<MeterStrip
					trackers={extras.trackers}
					onopen={() => {
						railSection = 'meters';
						railOpen = true;
					}}
				/>
			{/if}
			<Composer
				bind:this={composer}
				{commands}
				{snippets}
				{busy}
				onsend={send}
				oncarryon={carryOn}
			/>
		</div>
		{#if extras}
			<aside class="rail" aria-label="Dials, meters and the prompt">
				<StoryRail {extras} bind:section={railSection} />
			</aside>
		{/if}
	</div>
</div>

<Sheet bind:open={railOpen} title="This story" hint={story?.name}>
	{#if extras}<StoryRail {extras} bind:section={railSection} />{/if}
</Sheet>

<RerollSheet bind:open={rerollOpen} onreroll={reroll} />

<Sheet
	open={menuFor !== null}
	title="Turn {menuFor?.sequence ?? ''}"
	hint={menuFor?.role === 'user' ? 'yours' : story?.character_name}
>
	{#if menuFor}
		{#if !cutConfirm}
			<div class="menu">
				<button type="button" class="btn" onclick={() => menuFor && branchFrom(menuFor)}
					>Branch from here</button
				>
				<button type="button" class="btn" onclick={() => (cutConfirm = true)}
					>Cut the story back to here</button
				>
				<button type="button" class="btn" onclick={() => menuFor && copyText(menuFor)}
					>Copy the text</button
				>
				<button type="button" class="btn ghost" onclick={() => (menuFor = null)}>Close</button>
			</div>
		{:else}
			<p class="muted">
				This hides {cutCount}
				{cutCount === 1 ? 'turn' : 'turns'} from turn {menuFor.sequence} on, and the memory built from
				them. The rows stay.
			</p>
			<div class="menu">
				<button type="button" class="btn danger" onclick={() => menuFor && cutFrom(menuFor)}
					>Cut {cutCount} {cutCount === 1 ? 'turn' : 'turns'}</button
				>
				<button type="button" class="btn ghost" onclick={() => (cutConfirm = false)}
					>Keep them</button
				>
			</div>
		{/if}
	{/if}
</Sheet>

<Sheet bind:open={storyMenu} title={story?.name ?? 'Story'} hint={sub}>
	{#if renaming}
		<label class="field">
			<span>Name</span>
			<input class="input" id="rename" type="text" bind:value={newName} maxlength="200" />
		</label>
		<div class="menu">
			<button type="button" class="btn primary" onclick={rename}>Save</button>
			<button type="button" class="btn ghost" onclick={() => (renaming = false)}>Cancel</button>
		</div>
	{:else}
		<div class="menu">
			<button
				type="button"
				class="btn"
				onclick={() => {
					newName = story?.name ?? '';
					renaming = true;
				}}>Rename</button
			>
			{#if newestReply}
				<button
					type="button"
					class="btn"
					onclick={() => {
						storyMenu = false;
						if (newestReply) void branchFrom(newestReply);
					}}>Branch from the end</button
				>
			{/if}
			<button type="button" class="btn danger" onclick={deleteStory}>Delete the story</button>
			<button type="button" class="btn ghost" onclick={() => (storyMenu = false)}>Close</button>
		</div>
	{/if}
</Sheet>

<style>
	.screen {
		height: 100%;
		display: flex;
		flex-direction: column;
	}
	.body {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
	}
	.column {
		display: flex;
		flex-direction: column;
		min-height: 0;
		min-width: 0;
	}
	.rail {
		display: none;
	}
	.convo {
		flex: 1;
		overflow: auto;
		padding: 12px 14px 16px;
		display: grid;
		gap: 12px;
		align-content: end;
		overscroll-behavior: contain;
	}
	.center {
		text-align: center;
		padding: 32px 16px;
	}
	.problem {
		color: var(--danger);
		padding: 16px;
	}
	.note {
		justify-self: center;
		width: min(100%, 560px);
		padding: 12px 14px;
		border-radius: var(--r-m);
		background: var(--surface);
		border: 1px dashed var(--line-strong);
		display: grid;
		gap: 6px;
		font-size: 0.92rem;
	}
	.note b {
		font-size: 0.85rem;
		color: var(--gold-text);
	}
	.note p {
		white-space: pre-wrap;
		color: var(--fg-2);
	}
	.note footer {
		display: flex;
		justify-content: space-between;
		font-size: 0.72rem;
	}
	.link {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--gold-text);
		font-weight: 600;
		font-size: 0.72rem;
		min-height: 32px;
	}
	.menu {
		display: grid;
		gap: 8px;
	}
	.btn.danger {
		background: var(--danger);
		color: #fff;
	}
	@media (min-width: 900px) {
		.screen {
			max-width: 1180px;
			margin: 0 auto;
		}
		.body {
			grid-template-columns: minmax(0, 1fr) 320px;
		}
		.rail {
			display: block;
			border-left: 1px solid var(--line);
			padding: 16px;
			overflow: auto;
			min-height: 0;
		}
		:global(.rail-button) {
			display: none;
		}
	}
</style>
