/**
 * What rides beside a conversation: the dials in force, the meters, the last prompt's layers
 * and the running cost. One place, read by the phone's sheet and the desktop's rail alike, and
 * refreshed after each turn.
 */

import {
	api,
	type Audit,
	type Dial,
	type StoryDial,
	type StorySpend,
	type Tracker
} from './api.ts';
import { parseContext, type Context } from './audit.ts';
import { toasts } from './toasts.svelte.ts';

export class Extras {
	pack = $state<Dial[]>([]);
	dials = $state<StoryDial[]>([]);
	trackers = $state<Tracker[]>([]);
	audit = $state<Audit | null>(null);
	spend = $state<StorySpend | null>(null);
	loaded = $state(false);

	constructor(readonly storyId: string) {}

	/** The newest reply's layers, as bars. */
	get context(): Context | null {
		return parseContext(this.audit?.turns[0]?.context);
	}

	async load() {
		try {
			[this.pack, this.dials, this.trackers] = await Promise.all([
				api.dialPack(),
				api.storyDials(this.storyId),
				api.trackers(this.storyId)
			]);
			await this.refresh();
			this.loaded = true;
		} catch (error) {
			toasts.show(
				'danger',
				'Could not read the story’s settings',
				error instanceof Error ? error.message : undefined
			);
		}
	}

	/** After a turn: the meters may have moved, the audit and the cost have a new line. */
	async refresh() {
		const [trackers, audit, spend] = await Promise.allSettled([
			api.trackers(this.storyId),
			api.audit(this.storyId),
			api.storySpend(this.storyId)
		]);
		if (trackers.status === 'fulfilled') this.trackers = trackers.value;
		if (audit.status === 'fulfilled') this.audit = audit.value;
		if (spend.status === 'fulfilled') this.spend = spend.value;
	}

	dial(key: string): Dial | undefined {
		return this.pack.find((d) => d.key === key);
	}

	async setDial(key: string, value: string) {
		try {
			const changed = await api.setDial(this.storyId, key, value);
			this.dials = this.dials.map((d) => (d.key === key ? changed : d));
		} catch (error) {
			toasts.show('danger', 'Not set', error instanceof Error ? error.message : undefined);
		}
	}

	async clearDial(key: string) {
		try {
			await api.clearDial(this.storyId, key);
			const dial = this.dial(key);
			this.dials = this.dials.map((d) =>
				d.key === key
					? {
							...d,
							stored: null,
							effective: dial?.default ?? null,
							label: labelOf(dial, dial?.default ?? null)
						}
					: d
			);
		} catch (error) {
			toasts.show('danger', 'Not cleared', error instanceof Error ? error.message : undefined);
		}
	}

	async addTracker(body: Parameters<typeof api.addTracker>[1]) {
		try {
			const added = await api.addTracker(this.storyId, body);
			this.trackers = [...this.trackers, added];
			return true;
		} catch (error) {
			toasts.show('danger', 'Meter not added', error instanceof Error ? error.message : undefined);
			return false;
		}
	}

	async setTracker(name: string, value: number) {
		try {
			const changed = await api.changeTracker(this.storyId, name, { value });
			this.trackers = this.trackers.map((t) => (t.name === name ? changed : t));
		} catch (error) {
			toasts.show('danger', 'Meter not set', error instanceof Error ? error.message : undefined);
		}
	}

	async removeTracker(name: string) {
		try {
			await api.removeTracker(this.storyId, name);
			this.trackers = this.trackers.filter((t) => t.name !== name);
		} catch (error) {
			toasts.show(
				'danger',
				'Meter not removed',
				error instanceof Error ? error.message : undefined
			);
		}
	}
}

/** A stored value as a screen shows it, mirroring the API's `dials.label`. */
export function labelOf(dial: Dial | undefined, value: string | null): string | null {
	if (!dial || value === null) return null;
	switch (dial.kind) {
		case 'scale': {
			const i = Number(value);
			return Number.isInteger(i) && dial.levels[i] ? dial.levels[i].label : value;
		}
		case 'toggle':
			return value === 'true' ? 'On' : 'Off';
		case 'choice':
			return dial.options.find((o) => o.key === value)?.label ?? value;
		case 'list':
			try {
				const items = JSON.parse(value) as unknown;
				return Array.isArray(items) ? items.join(', ') : value;
			} catch {
				return value;
			}
		case 'text':
			return value;
	}
}
