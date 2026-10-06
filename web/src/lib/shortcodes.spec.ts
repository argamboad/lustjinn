import { describe, expect, it } from 'vitest';
import { EMOJI } from './emoji';
import { appendSnippet, expandEmoji, findEmoji, searchEmoji, tokenAt } from './shortcodes';

describe('tokenAt', () => {
	it('finds the shortcode being typed at the caret', () => {
		expect(tokenAt('I :sm', 5)).toEqual({ start: 2, length: 3, query: 'sm' });
		expect(tokenAt(':storm', 6)).toEqual({ start: 0, length: 6, query: 'storm' });
	});

	it('ignores a colon inside a word, so times and URLs never open the list', () => {
		expect(tokenAt('at 10:30', 8)).toBeNull();
		expect(tokenAt('https://x', 9)).toBeNull();
		expect(tokenAt('plain', 5)).toBeNull();
	});

	it('gives up on an absurdly long name', () => {
		expect(tokenAt(':' + 'a'.repeat(40), 41)).toBeNull();
	});
});

describe('expandEmoji', () => {
	it('replaces closed shortcodes and leaves snippet triggers and times alone', () => {
		expect(expandEmoji('I wave :wave: at 10:30 :storm and :nope: end')).toBe(
			'I wave 👋 at 10:30 :storm and :nope: end'
		);
	});

	it('ports the whole donor table', () => {
		expect(EMOJI.length).toBeGreaterThan(200);
		expect(findEmoji('fire')).toBe('🔥');
		expect(findEmoji('FIRE')).toBe('🔥');
		expect(findEmoji('no-such-thing')).toBeNull();
	});
});

describe('searchEmoji', () => {
	it('puts names that start with the query first, then keyword matches', () => {
		const found = searchEmoji('hap').map((e) => e.name);
		expect(found[0]).toBe('smile'); // keyword "happy" — nothing starts with "hap"
		expect(
			searchEmoji('smi')
				.map((e) => e.name)
				.slice(0, 2)
		).toEqual(['smile', 'smiley']);
		expect(searchEmoji('').length).toBe(8);
	});
});

describe('appendSnippet', () => {
	it('adds a space only when the draft needs one', () => {
		expect(appendSnippet('', 'Rain.')).toBe('Rain.');
		expect(appendSnippet('She waits ', 'Rain.')).toBe('She waits Rain.');
		expect(appendSnippet('She waits', 'Rain.')).toBe('She waits Rain.');
	});
});
