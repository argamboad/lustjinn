import { describe, expect, it } from 'vitest';
import { SseParser } from './sse';

describe('SseParser', () => {
	it('yields an event once its blank line has arrived, whatever the chunking', () => {
		const parser = new SseParser();
		expect(parser.push('event: delta\ndata: {"te')).toEqual([]);
		expect(parser.push('xt": "She"}\n\nev')).toEqual([{ event: 'delta', data: '{"text": "She"}' }]);
		expect(parser.push('ent: done\ndata: {}\n\n')).toEqual([{ event: 'done', data: '{}' }]);
	});

	it('skips comments and keep-alives and keeps multi-line data', () => {
		const parser = new SseParser();
		expect(parser.push(': OPENROUTER PROCESSING\n\ndata: one\ndata: two\n\n')).toEqual([
			{ event: null, data: 'one\ntwo' }
		]);
	});

	it('accepts CRLF line endings and a data field with no space after the colon', () => {
		const parser = new SseParser();
		expect(parser.push('event:delta\r\ndata:x\r\n\r\n')).toEqual([{ event: 'delta', data: 'x' }]);
	});
});
