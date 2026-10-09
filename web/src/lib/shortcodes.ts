/**
 * Shortcodes in the composer: `:name` opens the picker, `:name:` is an emoji, a bare `:name` is a
 * snippet trigger the API expands when the message is stored (chapter 4). The rules are the
 * donor's ShortcodeScanner: a colon opens a word only after whitespace or at the start, so a
 * clock time or a URL never pops the list open, and a name is at most 32 characters.
 */

import { emojiTable, type Shortcode } from './emoji.ts';

export const MAX_NAME = 32;

export interface Token {
	/** Where the colon is. */
	start: number;
	/** Through the caret. */
	length: number;
	query: string;
}

function isName(c: string): boolean {
	return /[A-Za-z0-9_+-]/.test(c);
}

/** The `:name` being typed at `caret`, or null. */
export function tokenAt(text: string, caret: number): Token | null {
	const at = Math.max(0, Math.min(caret, text.length));
	let start = at;
	while (start > 0 && isName(text[start - 1])) start--;
	if (start === 0 || text[start - 1] !== ':') return null;
	const colon = start - 1;
	if (colon > 0 && !/\s/.test(text[colon - 1])) return null;
	const query = text.slice(start, at);
	if (query.length > MAX_NAME) return null;
	return { start: colon, length: at - colon, query };
}

export function findEmoji(name: string): string | null {
	const wanted = name.toLowerCase();
	return emojiTable().find((e) => e.name === wanted)?.emoji ?? null;
}

/** Emoji whose name or keywords match the query, best first; the whole list for an empty query. */
export function searchEmoji(query: string, limit = 8): Shortcode[] {
	const q = query.toLowerCase();
	const all = emojiTable();
	if (!q) return all.slice(0, limit);
	const starts = all.filter((e) => e.name.startsWith(q));
	const contains = all.filter(
		(e) => !e.name.startsWith(q) && (e.name.includes(q) || e.keywords.includes(q))
	);
	return [...starts, ...contains].slice(0, limit);
}

/** `:name:` pairs replaced by their emoji; everything else, snippet triggers included, as it was. */
export function expandEmoji(text: string): string {
	let out = '';
	let i = 0;
	while (i < text.length) {
		const opens = text[i] === ':' && (i === 0 || /\s/.test(text[i - 1]));
		if (!opens) {
			out += text[i++];
			continue;
		}
		let end = i + 1;
		while (end < text.length && isName(text[end]) && end - i <= MAX_NAME) end++;
		const name = text.slice(i + 1, end);
		const emoji = name && text[end] === ':' ? findEmoji(name) : null;
		if (emoji) {
			out += emoji;
			i = end + 1;
		} else {
			out += text[i++];
		}
	}
	return out;
}

/** A snippet's text added to a draft: straight on when it is empty or ends in space, after a
 * space otherwise — the donor's rule. */
export function appendSnippet(draft: string, text: string): string {
	return draft.length === 0 || /\s$/.test(draft) ? draft + text : `${draft} ${text}`;
}
