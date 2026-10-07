"""Word completion from a word list (``WordList.cs`` and ``Words.txt``): typing long prose in a
terminal is the one place a dictionary earns its keep.

The list is the donor's — common English words, lower-case, three letters or more — read once
from the package. A word is offered only once three letters are typed, never mid-word (that is
an edit, not a write), never inside a contraction, and the shortest completions come first,
the word already typed in full never among them. What is inserted keeps the capitalisation the
reader was using.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Final

MINIMUM_PREFIX: Final = 3
APOSTROPHES: Final = frozenset({"'", "\u2019"})  # the typewriter one and the curly one


@dataclass(frozen=True, slots=True)
class WordToken:
    start: int
    length: int
    prefix: str


@cache
def all_words() -> tuple[str, ...]:
    """The dictionary, sorted and lower-case, from ``words.txt`` beside this module."""
    text = files("lustjinn_tui").joinpath("words.txt").read_text(encoding="utf-8")
    kept = {
        line.strip().lower()
        for line in text.splitlines()
        if len(line.strip()) >= MINIMUM_PREFIX and line.strip().isascii() and line.strip().isalpha()
    }
    return tuple(sorted(kept))


def token_at(line: str, column: int) -> WordToken | None:
    """The word being finished at ``column``, or None when completion should stay out of the
    way: mid-word, inside a contraction, or with fewer than three letters to go on."""
    caret = max(0, min(column, len(line)))
    if caret < len(line) and (line[caret].isalpha() or line[caret] in APOSTROPHES):
        return None
    start = caret
    while start > 0 and line[start - 1].isalpha():
        start -= 1
    prefix = line[start:caret]
    if len(prefix) < MINIMUM_PREFIX:
        return None
    if start > 0 and line[start - 1] in APOSTROPHES:
        return None
    return WordToken(start, len(prefix), prefix)


def suggest(prefix: str | None, limit: int = 7) -> list[str]:
    """The words that start with ``prefix``, shortest first, the prefix itself left out."""
    if limit <= 0 or not prefix or len(prefix) < MINIMUM_PREFIX:
        return []
    words = all_words()
    lower = prefix.lower()
    found: list[str] = []
    for i in range(bisect_left(words, lower), len(words)):
        word = words[i]
        if not word.startswith(lower):
            break
        if len(word) != len(lower):
            found.append(word)
    found.sort(key=lambda w: (len(w), w))
    return found[:limit]


def match_case(typed: str, word: str) -> str:
    """The completion in the reader's capitalisation: all caps past one letter, an initial
    capital, or as the list has it."""
    if not typed or not word:
        return word
    if len(typed) > 1 and all(not c.isalpha() or c.isupper() for c in typed):
        return word.upper()
    if typed[0].isupper():
        return word[0].upper() + word[1:]
    return word
