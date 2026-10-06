/** The story list, kept across screens so coming back from a story does not reload it. */

import { api, type Story } from './api.ts';

class Stories {
	list = $state<Story[] | null>(null);
	loading = $state(false);
	problem = $state<string | null>(null);

	async refresh() {
		this.loading = true;
		this.problem = null;
		try {
			this.list = await api.stories();
		} catch (error) {
			this.problem = error instanceof Error ? error.message : 'The stories could not be read.';
		} finally {
			this.loading = false;
		}
	}

	/** Puts a changed story at the top, or adds it. */
	touch(story: Story) {
		const rest = (this.list ?? []).filter((s) => s.id !== story.id);
		this.list = [story, ...rest];
	}

	remove(id: string) {
		this.list = (this.list ?? []).filter((s) => s.id !== id);
	}
}

export const stories = new Stories();
