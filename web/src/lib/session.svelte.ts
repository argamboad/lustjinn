/** Whether the reader is signed in, as the screens read it. The token itself lives in `api`. */

import { api, token, whenSignedOut } from './api.ts';

class Session {
	signedIn = $state(token.get() !== null);
	/** Why the sign-in screen is showing again, when it is not the first time. */
	note = $state<string | null>(null);

	constructor() {
		whenSignedOut(() => {
			if (this.signedIn) this.note = 'You were signed out. Sign in again to carry on.';
			this.signedIn = false;
		});
	}

	async signIn(username: string, password: string) {
		await api.signIn(username, password);
		this.note = null;
		this.signedIn = true;
	}

	signOut() {
		api.signOut();
		this.note = null;
		this.signedIn = false;
	}
}

export const session = new Session();
