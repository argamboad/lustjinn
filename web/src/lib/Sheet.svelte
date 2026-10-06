<script lang="ts">
	import type { Snippet } from 'svelte';

	/** A bottom sheet on a phone, a centred dialog on a wide screen. Closes on the scrim, on
	 * Escape, or from inside through `onclose`. */
	let {
		open = $bindable(false),
		title,
		hint,
		children
	}: { open?: boolean; title: string; hint?: string; children: Snippet } = $props();

	function close() {
		open = false;
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') close();
	}
</script>

<svelte:window {onkeydown} />

{#if open}
	<div class="scrim" role="presentation" onclick={close}></div>
	<div class="sheet" role="dialog" aria-modal="true" aria-label={title}>
		<div class="grab" aria-hidden="true"></div>
		<h3>
			<span>{title}</span>
			{#if hint}<small>{hint}</small>{/if}
		</h3>
		<div class="content">
			{@render children()}
		</div>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		background: var(--scrim);
		z-index: 30;
	}
	.sheet {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 31;
		max-height: calc(100% - 48px - var(--safe-top));
		overflow: auto;
		background: var(--surface);
		border-radius: 28px 28px 0 0;
		border-top: 1px solid var(--line-strong);
		box-shadow: var(--shadow);
		padding: 10px 18px calc(18px + var(--safe-bottom));
		display: grid;
		gap: 16px;
		animation: up 0.28s cubic-bezier(0.2, 0.8, 0.2, 1);
	}
	@keyframes up {
		from {
			transform: translateY(40px);
			opacity: 0;
		}
	}
	.grab {
		width: 40px;
		height: 5px;
		border-radius: 3px;
		background: var(--line-strong);
		justify-self: center;
	}
	h3 {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 10px;
		font-size: 1.05rem;
	}
	h3 small {
		color: var(--muted);
		font-weight: 500;
		font-size: 0.75rem;
	}
	.content {
		display: grid;
		gap: 16px;
	}
	@media (min-width: 720px) {
		.sheet {
			left: 50%;
			right: auto;
			bottom: auto;
			top: 50%;
			transform: translate(-50%, -50%);
			width: min(520px, calc(100% - 32px));
			border-radius: var(--r-l);
			border: 1px solid var(--line-strong);
			padding: 18px 22px 22px;
			animation: none;
		}
		.grab {
			display: none;
		}
	}
</style>
