<script lang="ts">
	import { paragraphs } from '#lib/prose.ts';

	/** A reply rendered as paragraphs of styled runs; the reader's own turns go through it too. */
	let { text }: { text: string } = $props();

	const blocks = $derived(paragraphs(text));
</script>

<div class="prose">
	{#each blocks as block, i (i)}
		<p>
			{#each block as run, j (j)}
				{#if run.kind === 'action'}<em class="action">{run.text}</em>
				{:else if run.kind === 'emphasis'}<strong class="emphasis">{run.text}</strong>
				{:else if run.kind === 'dialogue'}<span class="dialogue">“{run.text}”</span>
				{:else}{run.text}{/if}
			{/each}
		</p>
	{/each}
</div>

<style>
	.prose {
		font-family: var(--font-prose);
		font-size: 0.95rem;
		line-height: 1.5;
		display: grid;
		gap: 0.5em;
		overflow-wrap: anywhere;
	}
	p {
		margin: 0;
		white-space: pre-wrap;
	}
	.action {
		color: var(--fg-2);
		font-style: italic;
	}
	.emphasis {
		color: var(--gold-text);
		font-weight: 500;
	}
	.dialogue {
		color: var(--fg);
	}
</style>
