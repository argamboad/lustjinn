import { describe, expect, it } from 'vitest';
import { parseContext } from './audit';

describe('parseContext', () => {
	it('reads the layers, what was dropped, the total and the budget', () => {
		expect(
			parseContext(
				'character 2360 · world 417 · history 32 (1 dropped) · memories 530 · total 3339/6000'
			)
		).toEqual({
			layers: [
				{ name: 'character', tokens: 2360, dropped: 0 },
				{ name: 'world', tokens: 417, dropped: 0 },
				{ name: 'history', tokens: 32, dropped: 1 },
				{ name: 'memories', tokens: 530, dropped: 0 }
			],
			total: 3339,
			budget: 6000
		});
	});

	it('accepts a total without a budget, and nothing at all', () => {
		expect(parseContext('character 10 · total 10')).toEqual({
			layers: [{ name: 'character', tokens: 10, dropped: 0 }],
			total: 10,
			budget: null
		});
		expect(parseContext(null)).toBeNull();
		expect(parseContext('')).toBeNull();
		expect(parseContext('nonsense')).toBeNull();
	});
});
