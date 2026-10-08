<script lang="ts">
	import { page } from '$app/state';

	/** The top-level sections in the app bar of every screen, on a wide screen: there the bottom
	 * tabs are hidden, and this is what takes the reader anywhere. The section lit is the one the
	 * screen belongs to — a story and its dials are Stories, the editor is Library. */
	const sections = [
		{ href: '/', label: 'Stories', owns: ['/', '/new', '/story'] },
		{ href: '/library', label: 'Library', owns: ['/library'] },
		{ href: '/you', label: 'You', owns: ['/you'] }
	];

	function current(owns: string[]): boolean {
		const path = page.url.pathname;
		return owns.some((p) => (p === '/' ? path === '/' : path === p || path.startsWith(p + '/')));
	}
</script>

<nav class="sections" aria-label="Sections">
	{#each sections as s (s.href)}
		<a href={s.href} class:on={current(s.owns)} aria-current={current(s.owns) ? 'page' : undefined}
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
