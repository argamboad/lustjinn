/**
 * Whether the API is awake. Render's free tier sleeps after a quiet quarter hour and takes
 * thirty to sixty seconds to wake; the static site opens instantly, so the first thing it does
 * is knock, and show the lamp until something answers. (Not `server.svelte.ts`: a file with
 * `.server.` in its name is server-only to SvelteKit, and this one runs in the browser.)
 */

import { api, Unreachable, whenUnreachable } from './api.ts';

export type ServerState = 'checking' | 'waking' | 'up' | 'down';

const FIRST_WAIT_MS = 2000;
const LONGEST_WAIT_MS = 6000;
const PATIENCE_MS = 150_000;
/** After this long, the screen stops promising "usually under a minute" and says so. */

class Server {
	state = $state<ServerState>('checking');
	attempts = $state(0);
	commit = $state<string | null>(null);
	private started = 0;
	private timer: ReturnType<typeof setTimeout> | null = null;
	private running = false;

	constructor() {
		whenUnreachable(() => this.lost());
	}

	/** Knocks until the API answers. Safe to call again: a second call joins the first. */
	async wake(): Promise<void> {
		if (this.running) return;
		this.running = true;
		this.started = Date.now();
		this.attempts = 0;
		if (this.state === 'up') this.state = 'checking';
		try {
			for (;;) {
				try {
					const health = await api.health();
					this.commit = health.commit;
					this.state = 'up';
					return;
				} catch (error) {
					if (!(error instanceof Unreachable)) {
						// It answered — with an error page, say. Up is up; the screens report the rest.
						this.state = 'up';
						return;
					}
					this.attempts += 1;
					const waited = Date.now() - this.started;
					this.state = waited > PATIENCE_MS ? 'down' : 'waking';
					await this.sleep(Math.min(FIRST_WAIT_MS * this.attempts, LONGEST_WAIT_MS));
				}
			}
		} finally {
			this.running = false;
		}
	}

	/** The reader asked to try again now, instead of waiting out the pause. */
	retry() {
		if (this.timer) {
			clearTimeout(this.timer);
			this.timer = null;
		}
		this.state = 'checking';
		if (!this.running) void this.wake();
	}

	/** Called by the API client when a call could not reach the server: back to the lamp. */
	lost() {
		if (this.state === 'up') {
			this.state = 'waking';
			void this.wake();
		}
	}

	private sleep(ms: number) {
		return new Promise<void>((resolve) => {
			this.timer = setTimeout(() => {
				this.timer = null;
				resolve();
			}, ms);
		});
	}
}

export const server = new Server();
