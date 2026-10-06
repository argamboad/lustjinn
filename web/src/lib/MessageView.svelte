<script lang="ts">
	import Prose from '#lib/Prose.svelte';
	import type { Message } from '#lib/api.ts';

	/** One turn in the conversation: the reader's gold-edged on the right, the character's on
	 * the left. The newest reply offers a reroll; every turn opens its menu on a long press. */
	let {
		message,
		streaming = false,
		newest = false,
		onreroll,
		onmenu
	}: {
		message: Pick<Message, 'role' | 'text'> & Partial<Message>;
		streaming?: boolean;
		newest?: boolean;
		onreroll?: () => void;
		onmenu?: () => void;
	} = $props();

	const mine = $derived(message.role === 'user');

	function shortModel(model: string | null | undefined): string | null {
		if (!model) return null;
		return model.split('/').pop() ?? model;
	}

	// A long press (or a right click) opens the turn's menu; a tap does nothing, so reading
	// is never interrupted.
	let timer: ReturnType<typeof setTimeout> | null = null;
	function press() {
		if (!onmenu || streaming) return;
		timer = setTimeout(() => {
			timer = null;
			onmenu?.();
		}, 450);
	}
	function release() {
		if (timer) clearTimeout(timer);
		timer = null;
	}
	function contextmenu(event: MouseEvent) {
		if (!onmenu || streaming) return;
		event.preventDefault();
		onmenu();
	}
</script>

<article
	class="msg"
	class:mine
	class:streaming
	onpointerdown={press}
	onpointerup={release}
	onpointercancel={release}
	onpointerleave={release}
	oncontextmenu={contextmenu}
>
	{#if message.text}
		<Prose text={message.text} />
	{:else if streaming}
		<span class="thinking muted">…</span>
	{/if}
	{#if !mine && !streaming}
		<footer class="meta">
			{#if message.fell_back_from}
				<span class="chip warn">written by the default</span>
			{/if}
			{#if message.model}<span class="k">{shortModel(message.model)}</span>{/if}
			{#if newest && onreroll}
				<button type="button" class="link" onclick={onreroll}>Reroll</button>
			{/if}
		</footer>
	{/if}
</article>

<style>
	.msg {
		max-width: min(92%, 680px);
		padding: 12px 14px;
		border-radius: var(--r-l);
		background: var(--them);
		border: 1px solid var(--line);
		border-bottom-left-radius: 8px;
		justify-self: start;
		position: relative;
		user-select: text;
		-webkit-touch-callout: none;
	}
	.mine {
		background: var(--you);
		border-color: var(--you-line);
		border-bottom-left-radius: var(--r-l);
		border-bottom-right-radius: 8px;
		justify-self: end;
	}
	.streaming::after {
		content: '';
		display: inline-block;
		width: 8px;
		height: 1em;
		background: var(--gold);
		margin-left: 3px;
		vertical-align: -2px;
		border-radius: 2px;
		animation: blink 1s steps(2) infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}
	.thinking {
		font-size: 1.4rem;
		line-height: 1;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		margin-top: 8px;
		font-size: 0.7rem;
		color: var(--muted);
	}
	.k {
		padding: 1px 7px;
		border-radius: 6px;
		background: var(--surface-2);
	}
	.chip.warn {
		font-size: 0.66rem;
		padding: 1px 7px;
	}
	.link {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--gold-text);
		font-weight: 600;
		font-size: 0.72rem;
		padding: 4px 6px;
		margin: -4px -6px -4px auto;
		min-height: 32px;
	}
</style>
