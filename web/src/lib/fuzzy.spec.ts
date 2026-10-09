import { describe, expect, it } from 'vitest';
import { match, matchAllTerms, rank } from './fuzzy';

// The donor's FuzzyMatcher tests, as the terminal's test_fuzzy.py has them.

function score(query: string, candidate: string): number {
	const found = match(query, candidate);
	expect(found).not.toBeNull();
	return found!.score;
}

describe('match', () => {
	it('matches a subsequence, case folded, and nothing else', () => {
		expect(match('prof', 'Professor')).not.toBeNull();
		expect(match('psr', 'Professor')).not.toBeNull();
		expect(match('PROF', 'professor')).not.toBeNull();
		expect(match('', 'anything')).toEqual({ score: 0, positions: [] });
		expect(match('xyz', 'Professor')).toBeNull();
		expect(match('rp', 'Professor')).toBeNull();
		expect(match('professorx', 'Professor')).toBeNull();
		expect(match('a', '')).toBeNull();
	});

	it('says where the characters were taken', () => {
		expect(match('pf', 'Professor')?.positions).toEqual([0, 3]);
	});

	it('prefers prefixes, word starts and literal runs', () => {
		expect(score('prof', 'Professor')).toBeGreaterThan(score('prof', 'Purple Roof Of Fame'));
		expect(score('cap', 'Captain')).toBeGreaterThan(score('cap', 'Escapade'));
		expect(score('ab', 'Alpha Bravo')).toBeGreaterThan(score('ab', 'Xaxbx'));
		expect(score('cap', 'Escapade')).toBeGreaterThan(score('cap', 'Cold And Precise'));
	});
});

describe('matchAllTerms', () => {
	it('needs every term, in any order', () => {
		expect(matchAllTerms('writer story', 'Story Writer')).not.toBeNull();
		expect(matchAllTerms('writer poet', 'Story Writer')).toBeNull();
		expect(matchAllTerms('prof', 'Professor')).toEqual(match('prof', 'Professor'));
		expect(matchAllTerms('   ', 'anything')).toEqual({ score: 0, positions: [] });
	});

	it('scores exactly as the terminal does', () => {
		// Computed by the terminal's fuzzy.py: the two clients must order a filter the same way.
		const theTerminals: [string, string, number | null][] = [
			['prof', 'Professor', 107],
			['psr', 'Professor', 10],
			['PROF', 'professor', 101],
			['cap', 'Captain', 98],
			['cap', 'Escapade', 55],
			['cap', 'Cold And Precise', 23],
			['ab', 'Alpha Bravo', 15],
			['ab', 'Xaxbx', 0],
			['writer story', 'Story Writer', 102],
			['yuki', 'Yuki yuu nekomiya, October 8', 88],
			['oct 8', 'Yuki yuu nekomiya, October 8', 16],
			['sea', 'Celestial - Ten days at sea', 18],
			['cts', 'Celestial - Ten days at sea', -8],
			['BJU', 'BJU - Music', 96],
			['mus', 'BJU - Music', 58],
			['anna', 'Anna Kistoff - Accidental Homewrecker', 79],
			['hw', 'Anna Kistoff - Accidental Homewrecker', -33],
			['🎉', 'Party 🎉 night', 36],
			['night', 'Party 🎉 night', 78],
			['zz', 'Professor', null]
		];
		for (const [query, candidate, expected] of theTerminals) {
			expect(matchAllTerms(query, candidate)?.score ?? null, `${query} in ${candidate}`).toBe(
				expected
			);
		}
	});
});

describe('rank', () => {
	it('keeps the matches, best first, ties in their order', () => {
		const names = ['Assistant', 'Professor', 'Story Ideas', 'Captain'];
		const ranked = rank(names, 'st', (n) => n);
		expect(ranked[0]).toBe('Story Ideas');
		expect(ranked).toContain('Assistant');
		expect(ranked).not.toContain('Captain');
		expect(rank(names, '', (n) => n)).toEqual(names);
		expect(rank(['aa', 'ab', 'ac'], 'a', (n) => n)).toEqual(['aa', 'ab', 'ac']);
	});
});
