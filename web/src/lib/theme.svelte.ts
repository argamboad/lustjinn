/** The theme: follows the system by default; a choice overrides it and is remembered on the device. */

import { browser } from '$app/env';

export type ThemeMode = 'system' | 'dark' | 'light';

const KEY = 'lustjinn-theme';

function remembered(): ThemeMode {
	if (!browser) return 'system';
	try {
		const saved = localStorage.getItem(KEY);
		return saved === 'dark' || saved === 'light' ? saved : 'system';
	} catch {
		return 'system';
	}
}

class Theme {
	mode = $state<ThemeMode>(remembered());

	/** What is actually showing: the choice, or what the system says when there is none. */
	get effective(): 'dark' | 'light' {
		if (this.mode !== 'system') return this.mode;
		if (browser && window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
		return 'dark';
	}

	set(mode: ThemeMode) {
		this.mode = mode;
		if (!browser) return;
		if (mode === 'system') delete document.documentElement.dataset.theme;
		else document.documentElement.dataset.theme = mode;
		try {
			if (mode === 'system') localStorage.removeItem(KEY);
			else localStorage.setItem(KEY, mode);
		} catch {
			/* a private window: the choice lasts the session */
		}
	}

	cycle() {
		const order: ThemeMode[] = ['system', 'dark', 'light'];
		this.set(order[(order.indexOf(this.mode) + 1) % order.length]);
	}
}

export const theme = new Theme();
