<script lang="ts">
	/** The logo as a tile: the app icon, the waking screen's lamp, the header's mark. */
	let {
		size = 44,
		glow = false,
		label = ''
	}: { size?: number; glow?: boolean; label?: string } = $props();
</script>

<img
	class="lamp"
	class:glow
	src="/icons/favicon.svg"
	alt={label}
	width={size}
	height={size}
	style:--size="{size}px"
	draggable="false"
/>

<style>
	.lamp {
		width: var(--size);
		height: var(--size);
		border-radius: calc(var(--size) * 0.26);
		display: block;
		user-select: none;
	}
	.glow {
		box-shadow:
			0 0 0 calc(var(--size) * 0.07) var(--gold-soft),
			0 0 calc(var(--size) * 0.5) var(--gold-glow);
		animation: breathe 2.4s ease-in-out infinite;
	}
	@keyframes breathe {
		50% {
			box-shadow:
				0 0 0 calc(var(--size) * 0.11) var(--gold-soft),
				0 0 calc(var(--size) * 0.8) var(--gold-glow);
			transform: translateY(-4px);
		}
	}
</style>
