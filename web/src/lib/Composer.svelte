<script lang="ts">
	import type { Command, EntryFull } from '#lib/api.ts';
	import { appendSnippet, searchEmoji, tokenAt } from '#lib/shortcodes.ts';
	import type { Shortcode } from '#lib/emoji.ts';

	/**
	 * Where the reader writes: a textarea that grows, a gold send button that becomes "Carry on"
	 * when there is nothing to send, the command palette on a leading slash with what each
	 * command costs, and the shortcode picker on a `:` — snippets from the library and emoji.
	 * Enter sends; Shift+Enter is a new line.
	 */
	let {
		commands = [],
		snippets = [],
		busy = false,
		onsend,
		oncarryon
	}: {
		commands?: Command[];
		snippets?: EntryFull[];
		busy?: boolean;
		onsend: (text: string) => void;
		oncarryon: () => void;
	} = $props();

	let text = $state('');
	let caret = $state(0);
	let box: HTMLTextAreaElement | undefined = $state();
	let selected = $state(0);
	let picking = $state(false); // the : button opened the full snippet list

	const empty = $derived(text.trim().length === 0);

	/** The palette shows while the first word is a slash command still being typed. */
	const typing = $derived.by(() => {
		const match = /^\/(\S*)$/.exec(text);
		return match ? match[1].toLowerCase() : null;
	});
	const commandMatches = $derived.by(() =>
		typing === null ? [] : commands.filter((c) => c.name.startsWith(typing))
	);

	/** The `:name` under the caret, and what it could be: a snippet (inserted as its text, the
	 * server expands a bare trigger too) or an emoji. */
	const token = $derived(tokenAt(text, caret));
	type Pick = { kind: 'snippet'; entry: EntryFull } | { kind: 'emoji'; code: Shortcode };
	const picks = $derived.by((): Pick[] => {
		if (picking) return snippets.map((entry) => ({ kind: 'snippet', entry }));
		if (!token) return [];
		const q = token.query.toLowerCase();
		const matched: Pick[] = snippets
			.filter((s) => s.name.toLowerCase().startsWith(q))
			.slice(0, 5)
			.map((entry) => ({ kind: 'snippet', entry }));
		return [...matched, ...searchEmoji(q, 6).map((code) => ({ kind: 'emoji' as const, code }))];
	});

	const open = $derived(commandMatches.length > 0 || picks.length > 0);
	const count = $derived(commandMatches.length || picks.length);

	$effect(() => {
		if (selected >= count) selected = 0;
	});

	export function focus() {
		box?.focus();
	}

	function grow() {
		if (!box) return;
		box.style.height = 'auto';
		box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
		caret = box.selectionStart ?? text.length;
	}

	function completeCommand(command: Command) {
		text = `/${command.name} `;
		place(text.length);
	}

	function insert(pick: Pick) {
		const value = pick.kind === 'snippet' ? pick.entry.text : pick.code.emoji;
		if (picking || !token) {
			text = appendSnippet(text, value);
			picking = false;
			place(text.length);
			return;
		}
		const before = text.slice(0, token.start);
		const after = text.slice(token.start + token.length);
		const spaced = pick.kind === 'emoji' && after && !/^\s/.test(after) ? ' ' : '';
		text = before + value + spaced + after;
		place(before.length + value.length + spaced.length);
	}

	function place(at: number) {
		requestAnimationFrame(() => {
			grow();
			box?.focus();
			box?.setSelectionRange(at, at);
			caret = at;
		});
	}

	function send() {
		if (busy) return;
		if (empty) {
			oncarryon();
			return;
		}
		onsend(text);
		text = '';
		caret = 0;
		requestAnimationFrame(grow);
	}

	function keydown(event: KeyboardEvent) {
		if (open) {
			if (event.key === 'ArrowDown') {
				event.preventDefault();
				selected = (selected + 1) % count;
				return;
			}
			if (event.key === 'ArrowUp') {
				event.preventDefault();
				selected = (selected - 1 + count) % count;
				return;
			}
			if (event.key === 'Escape') {
				picking = false;
				if (token) {
					// Leave the text; the list closes until the next character.
					caret = -1;
				}
				return;
			}
			const exactCommand = commandMatches.length > 0 && commandMatches[selected].name === typing;
			if (event.key === 'Tab' || (event.key === 'Enter' && !exactCommand)) {
				event.preventDefault();
				if (commandMatches.length > 0) completeCommand(commandMatches[selected]);
				else insert(picks[selected]);
				return;
			}
		}
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			send();
		}
	}
</script>

<div class="composer">
	{#if commandMatches.length > 0}
		<div class="palette" role="listbox" aria-label="Commands">
			{#each commandMatches as command, i (command.name)}
				<button
					type="button"
					role="option"
					aria-selected={i === selected}
					class:sel={i === selected}
					onclick={() => completeCommand(command)}
				>
					<code>{command.usage}</code>
					<span>{command.summary}</span>
					<small class={command.cost}>{command.cost}</small>
				</button>
			{/each}
		</div>
	{:else if picks.length > 0}
		<div class="palette" role="listbox" aria-label={picking ? 'Snippets' : 'Snippets and emoji'}>
			{#each picks as pick, i (pick.kind === 'snippet' ? 's:' + pick.entry.id : 'e:' + pick.code.name)}
				<button
					type="button"
					role="option"
					aria-selected={i === selected}
					class:sel={i === selected}
					onclick={() => insert(pick)}
				>
					{#if pick.kind === 'snippet'}
						<code>:{pick.entry.name}</code>
						<span class="prose">{pick.entry.preview}</span>
						<small>snippet</small>
					{:else}
						<code class="emoji">{pick.code.emoji}</code>
						<span>:{pick.code.name}:</span>
						<small>emoji</small>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
	<div class="box" class:busy>
		<button
			type="button"
			class="round"
			aria-label="Insert a snippet"
			aria-pressed={picking}
			disabled={busy || snippets.length === 0}
			title={snippets.length === 0 ? 'No snippets in the library yet' : 'Insert a snippet'}
			onclick={() => (picking = !picking)}>:</button
		>
		<textarea
			id="composer"
			bind:this={box}
			bind:value={text}
			oninput={grow}
			onkeydown={keydown}
			onclick={grow}
			onkeyup={grow}
			rows="1"
			placeholder="Write your turn, / for a command, : for a snippet"
			aria-label="Your turn"
			disabled={busy}
			enterkeyhint="send"></textarea>
		<button
			type="button"
			class="send"
			class:carry={empty}
			onclick={send}
			disabled={busy}
			aria-label={empty ? 'Carry on' : 'Send'}
		>
			{#if empty}
				<span class="carry-label">Carry on ›</span>
			{:else}
				<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
					><path d="M12 4l7 7-1.4 1.4L13 7.8V20h-2V7.8l-4.6 4.6L5 11z" fill="currentColor" /></svg
				>
			{/if}
		</button>
	</div>
</div>

<style>
	.composer {
		position: relative;
		padding: 6px 10px calc(8px + var(--safe-bottom));
		border-top: 1px solid var(--line);
		background: color-mix(in srgb, var(--bg) 90%, transparent);
		backdrop-filter: blur(12px);
	}
	.box {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 6px;
		align-items: end;
		background: var(--surface-2);
		border: 1px solid var(--line-strong);
		border-radius: 24px;
		padding: 6px 6px 6px 6px;
	}
	.box:focus-within {
		border-color: var(--gold);
		box-shadow: 0 0 0 4px var(--gold-soft);
	}
	.box.busy {
		opacity: 0.7;
	}
	.round {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		border: 0;
		background: transparent;
		color: var(--fg-2);
		font-family: var(--font-mono);
		font-size: 1.1rem;
		font-weight: 500;
		display: grid;
		place-items: center;
	}
	.round[aria-pressed='true'] {
		background: var(--gold-soft);
		color: var(--gold-text);
	}
	.round:disabled {
		opacity: 0.4;
	}
	textarea {
		font-family: var(--font-prose);
		font-size: 1rem;
		background: transparent;
		border: 0;
		color: var(--fg);
		resize: none;
		padding: 9px 0;
		min-height: 40px;
		max-height: 160px;
		width: 100%;
		outline: none;
		line-height: 1.4;
	}
	textarea::placeholder {
		font-family: var(--font-ui);
		color: var(--muted);
	}
	.send {
		height: 40px;
		min-width: 40px;
		border-radius: 20px;
		border: 0;
		background: var(--gold);
		color: var(--gold-ink);
		display: grid;
		place-items: center;
		font-weight: 600;
		font-size: 0.85rem;
		padding: 0;
	}
	.send.carry {
		padding: 0 14px;
		background: transparent;
		color: var(--gold-text);
		border: 1px solid var(--you-line);
	}
	.send:disabled {
		opacity: 0.6;
	}
	.palette {
		position: absolute;
		left: 12px;
		right: 12px;
		bottom: calc(100% - 4px);
		max-height: 50vh;
		overflow: auto;
		background: var(--raised);
		border: 1px solid var(--line-strong);
		border-radius: var(--r-m);
		box-shadow: var(--shadow);
		display: grid;
	}
	.palette button {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 10px;
		align-items: baseline;
		padding: 10px 14px;
		border: 0;
		border-bottom: 1px solid var(--line);
		background: transparent;
		color: var(--fg);
		text-align: left;
		font-size: 0.86rem;
		min-height: 44px;
	}
	.palette button:last-child {
		border-bottom: 0;
	}
	.palette .sel {
		background: var(--gold-soft);
	}
	.palette code {
		color: var(--gold-text);
		white-space: nowrap;
	}
	.palette code.emoji {
		font-family: inherit;
		font-size: 1.1rem;
	}
	.palette span {
		color: var(--fg-2);
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.palette small {
		color: var(--muted);
		font-size: 0.68rem;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}
	.palette small.billed {
		color: var(--warn);
	}
</style>
