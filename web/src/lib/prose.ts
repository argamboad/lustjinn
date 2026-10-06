/**
 * A reply as runs: narration, *action*, **emphasis** and "dialogue". It is how a reply reads as
 * a scene rather than a wall of text. The rules are the donor's (`ProseFormat.cs`), ported as
 * rules and not as markup:
 *
 * - `*…*` is action and `**…**` is emphasis; a single run is never closed by the first half of
 *   a double marker, nor a double run by a lone asterisk inside it. A marker followed or preceded
 *   by whitespace is not a marker (`2 * 3`).
 * - `"…"` and `“…”` are dialogue, and must close on the same line.
 * - What the markers wrapped is kept; the markers themselves are not.
 */

export type RunKind = 'narration' | 'action' | 'emphasis' | 'dialogue';

export interface Run {
	kind: RunKind;
	text: string;
}

const CLOSERS: Record<string, string> = { '"': '"', '“': '”' };

function isSpace(c: string | undefined): boolean {
	return c !== undefined && /\s/.test(c);
}

function closingStar(text: string, from: number, doubled: boolean): number | null {
	if (from >= text.length || isSpace(text[from])) return null;
	for (let i = from; i < text.length; i++) {
		if (text[i] !== '*') continue;
		const isDouble = text[i + 1] === '*';
		if (isDouble !== doubled) continue;
		return i > from && !isSpace(text[i - 1]) ? i : null;
	}
	return null;
}

function closingQuote(text: string, from: number, closer: string): number | null {
	if (from >= text.length || isSpace(text[from])) return null;
	const close = text.indexOf(closer, from);
	if (close < 0 || close === from) return null;
	// Dialogue does not span lines: a quote left open is just a quote mark.
	return text.slice(from, close).includes('\n') ? null : close;
}

/** Splits one paragraph (or a whole reply) into runs. Adjacent narration is one run. */
export function runs(text: string): Run[] {
	const found: Run[] = [];
	let plain = '';
	const flush = () => {
		if (plain) found.push({ kind: 'narration', text: plain });
		plain = '';
	};
	let i = 0;
	while (i < text.length) {
		const here = text[i];
		if (here === '*') {
			const doubled = text[i + 1] === '*';
			const marker = doubled ? 2 : 1;
			const close = closingStar(text, i + marker, doubled);
			if (close !== null) {
				flush();
				found.push({ kind: doubled ? 'emphasis' : 'action', text: text.slice(i + marker, close) });
				i = close + marker;
				continue;
			}
		} else if (here in CLOSERS) {
			const close = closingQuote(text, i + 1, CLOSERS[here]);
			if (close !== null) {
				flush();
				found.push({ kind: 'dialogue', text: text.slice(i + 1, close) });
				i = close + 1;
				continue;
			}
		}
		plain += here;
		i++;
	}
	flush();
	return found;
}

/** A reply as paragraphs of runs: blank lines divide paragraphs, as they do in the transcript. */
export function paragraphs(text: string): Run[][] {
	return text
		.replace(/\r\n/g, '\n')
		.split(/\n{2,}/)
		.map((block) => block.trim())
		.filter((block) => block.length > 0)
		.map(runs);
}
