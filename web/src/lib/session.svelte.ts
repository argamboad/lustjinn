/** Whether the reader is signed in, as the screens read it. The token itself lives in `api`. */

import { api, token, whenSignedOut } from './api';

class Session {
	signedIn = $state(token.get() !== null);

	constructor() {
		whenSignedOut(() => {
			this.signedIn = false;
		});
	}

	async signIn(username: string, password: string) {
		await api.signIn(username, password);
		this.signedIn = true;
	}

	signOut() {
		api.signOut();
		this.signedIn = false;
	}
}

export const session = new Session();
