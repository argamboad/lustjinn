<script lang="ts">
	import { toasts } from '#lib/toasts.svelte.ts';
</script>

<div class="toasts" aria-live="polite">
	{#each toasts.list as toast (toast.id)}
		<div class="toast {toast.tone}" role="status">
			<span class="ic" aria-hidden="true">
				{toast.tone === 'warn'
					? '!'
					: toast.tone === 'danger'
						? '×'
						: toast.tone === 'ok'
							? '✓'
							: 'i'}
			</span>
			<div class="body">
				<b>{toast.title}</b>
				{#if toast.detail}<small>{toast.detail}</small>{/if}
			</div>
			<button
				type="button"
				class="close"
				aria-label="Dismiss"
				onclick={() => toasts.dismiss(toast.id)}>×</button
			>
		</div>
	{/each}
</div>

<style>
	.toasts {
		position: fixed;
		left: 12px;
		right: 12px;
		bottom: calc(12px + var(--safe-bottom));
		display: grid;
		gap: 8px;
		justify-items: center;
		pointer-events: none;
		z-index: 50;
	}
	.toast {
		pointer-events: auto;
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 10px;
		align-items: start;
		width: min(100%, 460px);
		padding: 12px 10px 12px 14px;
		border-radius: var(--r-m);
		background: var(--raised);
		border: 1px solid var(--line-strong);
		box-shadow: var(--shadow);
		animation: rise 0.25s cubic-bezier(0.2, 0.8, 0.2, 1);
	}
	@keyframes rise {
		from {
			transform: translateY(12px);
			opacity: 0;
		}
	}
	.ic {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-size: 0.8rem;
		font-weight: 700;
		color: #0a0d1b;
		background: var(--info);
		margin-top: 1px;
	}
	.warn .ic {
		background: var(--warn);
	}
	.danger .ic {
		background: var(--danger);
	}
	.ok .ic {
		background: var(--ok);
	}
	.body {
		min-width: 0;
		display: grid;
		gap: 2px;
	}
	.body b {
		font-weight: 600;
		font-size: 0.92rem;
	}
	.body small {
		color: var(--fg-2);
		font-size: 0.82rem;
		overflow-wrap: anywhere;
	}
	.close {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--muted);
		font-size: 1.1rem;
		line-height: 1;
		padding: 2px 6px;
		min-width: 32px;
		min-height: 32px;
	}
</style>
