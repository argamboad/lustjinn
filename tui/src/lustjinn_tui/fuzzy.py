"""The donor's fuzzy matcher (``FuzzyMatcher.cs``), scoring and all: the story filter, the command
palette and the emoji picker rank with it.

A query matches a candidate when its characters appear in order (a subsequence), case folded.
The score rewards adjacent matches (+8), matches at a word start (+12) and an exact case (+2),
charges the first match for every character skipped before it (-1 each, at most -12) and the
candidate for being longer than the query (-1 each, at most -40), then adds +40 when the query
occurs literally and +30 more when it does so at the very start. Several words in a query must
all match, in any order; the score is their integer mean.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

ADJACENT: Final = 8
WORD_START: Final = 12
CASE_MATCH: Final = 2
LEADING_CAP: Final = 12
UNMATCHED_CAP: Final = 40
SUBSTRING: Final = 40
PREFIX: Final = 30


@dataclass(frozen=True, slots=True)
class Match:
    score: int
    positions: tuple[int, ...]


def _word_start(candidate: str, i: int) -> bool:
    if i == 0:
        return True
    before = candidate[i - 1]
    return not before.isalnum() or (before.islower() and candidate[i].isupper())


def match(query: str, candidate: str) -> Match | None:
    """Greedy, left to right: each query character takes the first match at or after the last."""
    if not query:
        return Match(0, ())
    if not candidate:
        return None
    folded_candidate = candidate.lower()
    score = 0
    positions: list[int] = []
    previous = -2
    at = 0
    for n, wanted in enumerate(query.lower()):
        found = folded_candidate.find(wanted, at)
        if found < 0:
            return None
        if found == previous + 1:
            score += ADJACENT
        if _word_start(candidate, found):
            score += WORD_START
        if candidate[found] == query[n]:
            score += CASE_MATCH
        if n == 0:
            score += max(-LEADING_CAP, -found)
        positions.append(found)
        previous = found
        at = found + 1
    score += max(-UNMATCHED_CAP, -(len(candidate) - len(query)))
    literal = folded_candidate.find(query.lower())
    if literal >= 0:
        score += SUBSTRING
        if literal == 0:
            score += PREFIX
    return Match(score, tuple(positions))


def match_all_terms(query: str, candidate: str) -> Match | None:
    """Every space-separated term must match, in any order; the score is their integer mean."""
    terms = [t for t in query.split(" ") if t.strip()]
    if not terms:
        return Match(0, ())
    if len(terms) == 1:
        return match(terms[0], candidate)
    scores: list[int] = []
    positions: set[int] = set()
    for term in terms:
        found = match(term.strip(), candidate)
        if found is None:
            return None
        scores.append(found.score)
        positions.update(found.positions)
    return Match(sum(scores) // len(scores), tuple(sorted(positions)))


def rank[T](items: Sequence[T], query: str, text: Callable[[T], str]) -> list[T]:
    """The items that match, best first; ties keep their order. A blank query keeps them all."""
    if not query.strip():
        return list(items)
    scored = [
        (found.score, i, item)
        for i, item in enumerate(items)
        if (found := match_all_terms(query, text(item))) is not None
    ]
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [item for _, _, item in scored]
