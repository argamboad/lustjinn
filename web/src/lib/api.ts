/**
 * The API, as the screens see it: typed calls over fetch, the bearer token on every request, and
 * the one streaming call read as server-sent events. The base URL is baked in at build time
 * (`VITE_API_URL`), the local API by default.
 */

import { readEvents } from './sse';

export const API_URL: string =
	(import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000';

const TOKEN_KEY = 'lustjinn-token';

export interface Token {
	access_token: string;
	token_type: 'bearer';
	expires_at: string;
}

export interface Health {
	status: 'ok';
	commit: string | null;
}

export type Role = 'user' | 'assistant' | 'system';

export interface Message {
	id: string;
	sequence: number;
	role: Role;
	text: string;
	model: string | null;
	provider: string | null;
	sent_at: string;
}

export interface Story {
	id: string;
	name: string;
	character_id: string;
	character_name: string;
	persona_id: string | null;
	persona_name: string | null;
	created_at: string;
	last_message_at: string | null;
	last_message_preview: string | null;
}

export interface StoryWithMessages extends Story {
	messages: Message[];
}

export interface Aside {
	id: string;
	sequence: number;
	question: string;
	answer: string;
	model: string | null;
	provider: string | null;
	asked_at: string;
}

/** How a `/send` stream ends: what was stored, or why nothing was. */
export type Done =
	| { kind: 'turn'; sent: Message | null; reply: Message; replayed: boolean }
	| { kind: 'aside'; aside: Aside }
	| { kind: 'said'; text: string }
	| { kind: 'error'; detail: string; sent: Message | null };

export interface Entry {
	id: string;
	name: string;
	hidden: boolean;
	version: number;
	updated_at: string;
	preview: string;
}

export interface EntryFull extends Entry {
	text: string;
	opening: string | null;
	used_by: string[];
}

export type Shelf = 'characters' | 'personas' | 'snippets';

export interface HistoryEntry {
	version: number;
	name: string;
	text: string;
	opening: string | null;
	saved_at: string;
}

export interface Defaults {
	default_persona_id: string | null;
	default_persona_name: string | null;
}

export interface StorySpend {
	story_id: string;
	name: string;
	calls: number;
	cost: string;
	discarded_calls: number;
	discarded_cost: string;
	unpriced: number;
	cached_share: number | null;
}

export interface SpendReport {
	calls: number;
	cost: string;
	discarded_cost: string;
	unpriced: number;
	by_story: StorySpend[];
}

export type DialKind = 'scale' | 'toggle' | 'choice' | 'list' | 'text';

export interface DialLevel {
	label: string;
	text: string | null;
	value: number | null;
	description: string | null;
}

export interface Dial {
	key: string;
	kind: DialKind;
	lever: 'prompt' | 'sampler' | 'both';
	maps: string | null;
	enabled: boolean;
	default: string | null;
	title: string;
	help: string;
	levels: DialLevel[];
	options: { key: string; label: string; text: string }[];
	on_text: string | null;
	template: string | null;
	accepts: string | null;
	examples: string[];
}

export interface StoryDial {
	key: string;
	title: string;
	kind: DialKind;
	enabled: boolean;
	stored: string | null;
	effective: string | null;
	label: string | null;
}

export interface Tracker {
	id: string;
	name: string;
	value: number;
	max: number;
	delta: number;
	note: string | null;
	means: string | null;
	anchors: string | null;
	rule: string | null;
	updated_at_sequence: number | null;
}

export interface NewTracker {
	name: string;
	value?: number;
	max?: number;
	means?: string | null;
	anchors?: string | null;
	rule?: string | null;
}

export interface TurnAudit {
	sequence: number;
	sent_at: string;
	hidden: boolean;
	model: string | null;
	provider: string | null;
	estimated_prompt_tokens: number | null;
	prompt_tokens: number | null;
	completion_tokens: number | null;
	context: string | null;
}

export interface Audit {
	turns: TurnAudit[];
}

export interface Command {
	name: string;
	usage: string;
	summary: string;
	cost: 'free' | 'billed' | 'write';
	needs_argument: boolean;
}

/** A refusal from the API, with the reason it gave, and the body for the few refusals that
 * carry more than a sentence (a library save over a newer version carries the entry as it is). */
export class ApiError extends Error {
	constructor(
		public readonly status: number,
		message: string,
		public readonly body: unknown = null
	) {
		super(message);
	}
}

/** The API could not be reached at all: asleep, offline, or down. */
export class Unreachable extends Error {}

export const token = {
	get(): string | null {
		try {
			return localStorage.getItem(TOKEN_KEY);
		} catch {
			return null;
		}
	},
	set(value: string | null) {
		try {
			if (value === null) localStorage.removeItem(TOKEN_KEY);
			else localStorage.setItem(TOKEN_KEY, value);
		} catch {
			/* a private window: signed in for this tab only */
		}
	}
};

/** Called when the API answers 401: the token is gone, and the session must say so. */
export let onSignedOut: () => void = () => {};
export function whenSignedOut(handler: () => void) {
	onSignedOut = handler;
}

/** Called when a call could not reach the API at all: the server store goes back to knocking. */
export let onUnreachable: () => void = () => {};
export function whenUnreachable(handler: () => void) {
	onUnreachable = handler;
}

function headers(json: boolean): HeadersInit {
	const found: Record<string, string> = {};
	if (json) found['Content-Type'] = 'application/json';
	const bearer = token.get();
	if (bearer) found['Authorization'] = `Bearer ${bearer}`;
	return found;
}

async function detailOf(response: Response): Promise<[string, unknown]> {
	let body: { detail?: unknown } = {};
	try {
		body = (await response.json()) as { detail?: unknown };
		if (typeof body.detail === 'string') return [body.detail, body.detail];
		if (Array.isArray(body.detail)) {
			const said = body.detail
				.map(
					(p: { loc?: unknown[]; msg?: string }) =>
						`${(p.loc ?? []).slice(-1)[0] ?? ''}: ${p.msg ?? ''}`
				)
				.join('; ');
			return [said, body.detail];
		}
		if (body.detail && typeof body.detail === 'object' && 'message' in body.detail) {
			return [String((body.detail as { message: unknown }).message), body.detail];
		}
	} catch {
		/* no JSON body */
	}
	return [`${response.status} ${response.statusText}`, body.detail ?? null];
}

async function call(method: string, path: string, body?: unknown): Promise<Response> {
	let response: Response;
	try {
		response = await fetch(`${API_URL}${path}`, {
			method,
			headers: headers(body !== undefined),
			body: body === undefined ? undefined : JSON.stringify(body)
		});
	} catch {
		if (path !== '/health') onUnreachable();
		throw new Unreachable('The server did not answer.');
	}
	if (response.status === 401) {
		token.set(null);
		onSignedOut();
	}
	if (!response.ok) {
		const [message, detail] = await detailOf(response);
		throw new ApiError(response.status, message, detail);
	}
	return response;
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
	return (await call(method, path, body)).json() as Promise<T>;
}

export const api = {
	health: () => json<Health>('GET', '/health'),

	async signIn(username: string, password: string): Promise<Token> {
		const issued = await json<Token>('POST', '/auth/sign-in', { username, password });
		token.set(issued.access_token);
		return issued;
	},
	signOut() {
		token.set(null);
	},

	stories: () => json<Story[]>('GET', '/stories'),
	story: (id: string) => json<StoryWithMessages>('GET', `/stories/${id}`),
	createStory: (body: { name: string; character_id: string; persona_id?: string | null }) =>
		json<StoryWithMessages>('POST', '/stories', body),
	renameStory: (id: string, name: string) => json<Story>('PATCH', `/stories/${id}`, { name }),
	deleteStory: (id: string) => call('DELETE', `/stories/${id}`).then(() => undefined),

	branch: (storyId: string, messageId: string, name?: string) =>
		json<StoryWithMessages>('POST', `/stories/${storyId}/branch`, {
			message_id: messageId,
			name: name ?? null
		}),
	deleteFrom: (storyId: string, messageId: string) =>
		json<{ story: StoryWithMessages; hidden: number }>(
			'DELETE',
			`/stories/${storyId}/messages/${messageId}`
		),

	commands: () => json<Command[]>('GET', '/commands'),
	dialPack: () => json<Dial[]>('GET', '/dials'),
	storyDials: (storyId: string) => json<StoryDial[]>('GET', `/stories/${storyId}/dials`),
	setDial: (storyId: string, key: string, value: string) =>
		json<StoryDial>('PUT', `/stories/${storyId}/dials/${key}`, { value }),
	clearDial: (storyId: string, key: string) =>
		call('DELETE', `/stories/${storyId}/dials/${key}`).then(() => undefined),
	trackers: (storyId: string) => json<Tracker[]>('GET', `/stories/${storyId}/trackers`),
	addTracker: (storyId: string, body: NewTracker) =>
		json<Tracker>('POST', `/stories/${storyId}/trackers`, body),
	changeTracker: (storyId: string, name: string, body: Partial<Omit<NewTracker, 'name'>>) =>
		json<Tracker>('PATCH', `/stories/${storyId}/trackers/${encodeURIComponent(name)}`, body),
	removeTracker: (storyId: string, name: string) =>
		call('DELETE', `/stories/${storyId}/trackers/${encodeURIComponent(name)}`).then(
			() => undefined
		),
	audit: (storyId: string) => json<Audit>('GET', `/stories/${storyId}/audit`),
	characters: () => json<Entry[]>('GET', '/library/characters'),
	personas: () => json<Entry[]>('GET', '/library/personas'),
	snippets: async (): Promise<EntryFull[]> => {
		const listed = await json<Entry[]>('GET', '/library/snippets');
		return Promise.all(listed.map((s) => json<EntryFull>('GET', `/library/snippets/${s.id}`)));
	},
	defaults: () => json<Defaults>('GET', '/library/settings'),
	setDefaults: (default_persona_id: string | null) =>
		json<Defaults>('PUT', '/library/settings', { default_persona_id }),
	entries: (shelf: Shelf, hidden = false) =>
		json<Entry[]>('GET', `/library/${shelf}${hidden ? '?hidden=true' : ''}`),
	entry: (shelf: Shelf, id: string) => json<EntryFull>('GET', `/library/${shelf}/${id}`),
	createEntry: (shelf: Shelf, body: { name: string; text: string; opening?: string | null }) =>
		json<EntryFull>('POST', `/library/${shelf}`, body),
	saveEntry: (
		shelf: Shelf,
		id: string,
		body: { version: number; name?: string; text?: string; opening?: string | null }
	) => json<EntryFull>('PATCH', `/library/${shelf}/${id}`, body),
	deleteEntry: (shelf: Shelf, id: string) =>
		call('DELETE', `/library/${shelf}/${id}`).then(() => undefined),
	history: (shelf: Shelf, id: string) =>
		json<HistoryEntry[]>('GET', `/library/${shelf}/${id}/history`),
	spend: (from?: string) =>
		json<SpendReport>('GET', from ? `/spend?from_at=${encodeURIComponent(from)}` : '/spend'),
	storySpend: (storyId: string) => json<StorySpend>('GET', `/stories/${storyId}/spend`),

	/**
	 * Sends what the reader typed and streams the reply: `onDelta` gets each piece of text as it
	 * arrives, and the promise resolves with how the stream ended. A refusal before the stream
	 * (a 4xx) rejects with an `ApiError`.
	 */
	send: (storyId: string, text: string, onDelta: (text: string) => void) =>
		streamed('POST', `/stories/${storyId}/send`, { text }, onDelta),
	reroll: (
		storyId: string,
		onDelta: (text: string) => void,
		body?: { reason: string; instructions?: string | null }
	) => streamed('POST', `/stories/${storyId}/reroll`, body ?? {}, onDelta),
	carryOn: (storyId: string, onDelta: (text: string) => void) =>
		streamed('POST', `/stories/${storyId}/continue`, undefined, onDelta)
};

async function streamed(
	method: string,
	path: string,
	body: unknown,
	onDelta: (text: string) => void
): Promise<Done> {
	const response = await call(method, path, body);
	if (!response.body) throw new Unreachable('The server sent no stream.');
	let done: Done | null = null;
	await readEvents(response.body, (event) => {
		if (event.event === 'delta') {
			onDelta((JSON.parse(event.data) as { text: string }).text);
		} else if (event.event === 'done' || event.event === 'error') {
			done = JSON.parse(event.data) as Done;
		}
	});
	if (done === null) throw new Unreachable('The stream ended without saying how.');
	return done;
}
