import { describe, expect, it } from 'vitest';
import { paragraphs, runs } from './prose';

describe('runs', () => {
	it('tells action, emphasis and dialogue from narration and drops the markers', () => {
		expect(runs('*She looks up.* "A week," she says, **not** smiling.')).toEqual([
			{ kind: 'action', text: 'She looks up.' },
			{ kind: 'narration', text: ' ' },
			{ kind: 'dialogue', text: 'A week,' },
			{ kind: 'narration', text: ' she says, ' },
			{ kind: 'emphasis', text: 'not' },
			{ kind: 'narration', text: ' smiling.' }
		]);
	});

	it('keeps plain text as one narration run', () => {
		expect(runs('The fog had come in early.')).toEqual([
			{ kind: 'narration', text: 'The fog had come in early.' }
		]);
		expect(runs('')).toEqual([]);
	});

	it('reads single and double markers side by side', () => {
		expect(runs('**a** *b*')).toEqual([
			{ kind: 'emphasis', text: 'a' },
			{ kind: 'narration', text: ' ' },
			{ kind: 'action', text: 'b' }
		]);
	});

	it('does not close a double run with a lone asterisk inside it', () => {
		expect(runs('**a *b** c')).toEqual([
			{ kind: 'emphasis', text: 'a *b' },
			{ kind: 'narration', text: ' c' }
		]);
	});

	it('treats a star beside whitespace as a star', () => {
		expect(runs('2 * 3 * 4')).toEqual([{ kind: 'narration', text: '2 * 3 * 4' }]);
		expect(runs('*open but never closed')).toEqual([
			{ kind: 'narration', text: '*open but never closed' }
		]);
	});

	it('reads curly quotes and leaves an unclosed or multi-line quote alone', () => {
		expect(runs('“Room seven.”')).toEqual([{ kind: 'dialogue', text: 'Room seven.' }]);
		expect(runs('She said "and left')).toEqual([{ kind: 'narration', text: 'She said "and left' }]);
		expect(runs('"one\ntwo"')).toEqual([{ kind: 'narration', text: '"one\ntwo"' }]);
		expect(runs('""')).toEqual([{ kind: 'narration', text: '""' }]);
	});
});

describe('paragraphs', () => {
	it('splits on blank lines and trims, whatever the line endings', () => {
		expect(paragraphs('*One.*\r\n\r\n\r\n"Two."\n\n')).toEqual([
			[{ kind: 'action', text: 'One.' }],
			[{ kind: 'dialogue', text: 'Two.' }]
		]);
	});
});
