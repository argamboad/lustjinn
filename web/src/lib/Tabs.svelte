<script lang="ts">
	import { page } from '$app/state';

	/** The bottom tabs of the top-level screens. */
	const tabs = [
		{ href: '/', label: 'Stories', icon: 'M4 5h16v3H4zM4 10.5h16v3H4zM4 16h10v3H4z' },
		{ href: '/you', label: 'You', icon: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 8a7 7 0 0 1 14 0z' }
	];

	function current(href: string): boolean {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<nav class="tabs" aria-label="Sections">
	{#each tabs as tab (tab.href)}
		<a
			href={tab.href}
			class:on={current(tab.href)}
			aria-current={current(tab.href) ? 'page' : undefined}
		>
			<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d={tab.icon} /></svg>
			<span>{tab.label}</span>
		</a>
	{/each}
</nav>

<style>
	.tabs {
		display: flex;
		border-top: 1px solid var(--line);
		background: color-mix(in srgb, var(--bg) 88%, transparent);
		backdrop-filter: blur(12px);
		padding: 6px 10px calc(6px + var(--safe-bottom));
		position: sticky;
		bottom: 0;
	}
	a {
		flex: 1;
		text-decoration: none;
		color: var(--muted);
		font-size: 0.68rem;
		font-weight: 500;
		display: grid;
		justify-items: center;
		gap: 2px;
		padding: 4px 0;
		min-height: 44px;
	}
	a.on {
		color: var(--gold-text);
	}
	svg path {
		fill: currentColor;
	}
	@media (min-width: 900px) {
		.tabs {
			display: none;
		}
	}
</style>
