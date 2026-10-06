<script lang="ts">
	import type { Command } from '#lib/api.ts';

	/**
	 * Where the reader writes: a textarea that grows, a gold send button that becomes "Carry on"
	 * when there is nothing to send, and the command palette that opens on a leading slash with
	 * what each command costs. Enter sends; Shift+Enter is a new line.
	 */
	let {
		commands = [],
		busy = false,
		onsend,
		oncarryon
	}: {
		commands?: Command[];
		busy?: boolean;
		onsend: (text: string) => void;
		oncarryon: () => void;
	} = $props();

	let text = $state('');
	let box: HTMLTextAreaElement | undefined = $state();
	let selected = $state(0);

	const empty = $derived(text.trim().length === 0);
	/** The palette shows while the first word is a slash command still being typed. */
	const typing = $derived.by(() => {
		const match = /^\/(\S*)$/.exec(text);
		return match ? match[1].toLowerCase() : null;
	});
	const matches = $derived.by(() => {
		if (typing === null) return [];
		return commands.filter((c) => c.name.startsWith(typing));
	});

	$effect(() => {
		if (selected >= matches.length) selected = 0;
	});

	export function focus() {
		box?.focus();
	}

	function grow() {
		if (!box) return;
		box.style.height = 'auto';
		box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
	}

	function complete(command: Command) {
		text = `/${command.name} `;
		grow();
		box?.focus();
	}

	function send() {
		if (busy) return;
		if (empty) {
			oncarryon();
			return;
		}
		onsend(text);
		text = '';
		requestAnimationFrame(grow);
	}

	function keydown(event: KeyboardEvent) {
		if (matches.length > 0 && typing !== null) {
			if (event.key === 'ArrowDown') {
				event.preventDefault();
				selected = (selected + 1) % matches.length;
				return;
			}
			if (event.key === 'ArrowUp') {
				event.preventDefault();
				selected = (selected - 1 + matches.length) % matches.length;
				return;
			}
			if (event.key === 'Tab' || (event.key === 'Enter' && matches[selected].name !== typing)) {
				event.preventDefault();
				complete(matches[selected]);
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
	{#if matches.length > 0}
		<div class="palette" role="listbox" aria-label="Commands">
			{#each matches as command, i (command.name)}
				<button
					type="button"
					role="option"
					aria-selected={i === selected}
					class:sel={i === selected}
					onclick={() => complete(command)}
				>
					<code>{command.usage}</code>
					<span>{command.summary}</span>
					<small class={command.cost}>{command.cost}</small>
				</button>
			{/each}
		</div>
	{/if}
	<div class="box" class:busy>
		<textarea
			id="composer"
			bind:this={box}
			bind:value={text}
			oninput={grow}
			onkeydown={keydown}
			rows="1"
			placeholder="Write your turn, or / for a command"
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
		padding: 8px 12px calc(10px + var(--safe-bottom));
		border-top: 1px solid var(--line);
		background: color-mix(in srgb, var(--bg) 90%, transparent);
		backdrop-filter: blur(12px);
	}
	.box {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 8px;
		align-items: end;
		background: var(--surface-2);
		border: 1px solid var(--line-strong);
		border-radius: 24px;
		padding: 6px 6px 6px 14px;
	}
	.box:focus-within {
		border-color: var(--gold);
		box-shadow: 0 0 0 4px var(--gold-soft);
	}
	.box.busy {
		opacity: 0.7;
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
		background: var(--raised);
		border: 1px solid var(--line-strong);
		border-radius: var(--r-m);
		box-shadow: var(--shadow);
		overflow: hidden;
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
