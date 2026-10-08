<script lang="ts">
	import { page } from '$app/state';

	/** The top-level sections in the app bar, for a wide screen: there the bottom tabs are
	 * hidden, and without this a reader on Library or You has only the browser's back button. */
	const sections = [
		{ href: '/', label: 'Stories' },
		{ href: '/library', label: 'Library' },
		{ href: '/you', label: 'You' }
	];

	function current(href: string): boolean {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<nav class="sections" aria-label="Sections">
	{#each sections as s (s.href)}
		<a href={s.href} class:on={current(s.href)} aria-current={current(s.href) ? 'page' : undefined}
			>{s.label}</a
		>
	{/each}
</nav>

<style>
	.sections {
		display: none;
		gap: 2px;
	}
	a {
		text-decoration: none;
		color: var(--fg-2);
		font-weight: 500;
		font-size: 0.9rem;
		padding: 6px 12px;
		border-radius: 999px;
	}
	a:hover {
		color: var(--fg);
	}
	a.on {
		color: var(--gold-text);
		background: var(--gold-soft);
	}
	/* The same width at which the bottom tabs hide: one or the other is always there. */
	@media (min-width: 900px) {
		.sections {
			display: flex;
		}
	}
</style>
