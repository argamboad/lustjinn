/**
 * The donor's fuzzy matcher (FuzzyMatcher.cs), ported from the terminal's `fuzzy.py` so both
 * clients rank a filter the same way (#135).
 *
 * A query matches a candidate when its characters appear in order (a subsequence), case folded.
 * The score rewards adjacent matches (+8), matches at a word start (+12) and an exact case (+2),
 * charges the first match for every character skipped before it (-1 each, at most -12) and the
 * candidate for being longer than the query (-1 each, at most -40), then adds +40 when the query
 * occurs literally and +30 more when it does so at the very start. Several words in a query must
 * all match, in any order; the score is their integer mean.
 *
 * Positions and lengths count code points, as Python does, so a name with an emoji in it scores
 * the same here as in the terminal.
 */

const ADJACENT = 8;
const WORD_START = 12;
const CASE_MATCH = 2;
const LEADING_CAP = 12;
const UNMATCHED_CAP = 40;
const SUBSTRING = 40;
const PREFIX = 30;

export interface Match {
	score: number;
	positions: number[];
}

const ALNUM = /[\p{L}\p{N}]/u;
const LOWER = /\p{Ll}/u;
const UPPER = /\p{Lu}/u;

function wordStart(candidate: string[], i: number): boolean {
	if (i === 0) return true;
	const before = candidate[i - 1];
	return !ALNUM.test(before) || (LOWER.test(before) && UPPER.test(candidate[i]));
}

function indexOf(chars: string[], wanted: string, from: number): number {
	for (let i = from; i < chars.length; i++) if (chars[i] === wanted) return i;
	return -1;
}

/** Greedy, left to right: each query character takes the first match at or after the last. */
export function match(query: string, candidate: string): Match | null {
	if (!query) return { score: 0, positions: [] };
	if (!candidate) return null;
	const chars = Array.from(candidate);
	const folded = Array.from(candidate.toLowerCase());
	const typed = Array.from(query);
	const wanted = Array.from(query.toLowerCase());
	let score = 0;
	const positions: number[] = [];
	let previous = -2;
	let at = 0;
	for (let n = 0; n < wanted.length; n++) {
		const found = indexOf(folded, wanted[n], at);
		if (found < 0) return null;
		if (found === previous + 1) score += ADJACENT;
		if (wordStart(chars, found)) score += WORD_START;
		if (chars[found] === typed[n]) score += CASE_MATCH;
		if (n === 0) score += Math.max(-LEADING_CAP, -found);
		positions.push(found);
		previous = found;
		at = found + 1;
	}
	score += Math.max(-UNMATCHED_CAP, -(chars.length - typed.length));
	const literal = candidate.toLowerCase().indexOf(query.toLowerCase());
	if (literal >= 0) {
		score += SUBSTRING;
		if (literal === 0) score += PREFIX;
	}
	return { score, positions };
}

/** Every space-separated term must match, in any order; the score is their integer mean. */
export function matchAllTerms(query: string, candidate: string): Match | null {
	const terms = query.split(' ').filter((t) => t.trim());
	if (terms.length === 0) return { score: 0, positions: [] };
	if (terms.length === 1) return match(terms[0], candidate);
	const scores: number[] = [];
	const positions = new Set<number>();
	for (const term of terms) {
		const found = match(term.trim(), candidate);
		if (!found) return null;
		scores.push(found.score);
		found.positions.forEach((p) => positions.add(p));
	}
	const sum = scores.reduce((a, b) => a + b, 0);
	return {
		score: Math.floor(sum / scores.length),
		positions: [...positions].sort((a, b) => a - b)
	};
}

/** The items that match, best first; ties keep their order. A blank query keeps them all. */
export function rank<T>(items: readonly T[], query: string, text: (item: T) => string): T[] {
	if (!query.trim()) return [...items];
	const scored: { score: number; i: number; item: T }[] = [];
	items.forEach((item, i) => {
		const found = matchAllTerms(query, text(item));
		if (found) scored.push({ score: found.score, i, item });
	});
	scored.sort((a, b) => b.score - a.score || a.i - b.i);
	return scored.map((s) => s.item);
}
