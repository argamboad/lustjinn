"""Stepping through text by grapheme cluster, not by code point (``Graphemes.cs``).

A pasted emoji is one character to the eye and several to the string: a family is four people
joined by zero-width joiners, a thumbs-up with a skin tone is two code points, a flag is two
regional indicators. Textual's text area moves and deletes by code point, so a backspace would
take one member of the family, or just the skin tone. These helpers find the cluster
boundaries so the composer treats an emoji as the one character it looks like.

The standard library has no grapheme segmentation, so this is the part of UAX #29 that matters
in a chat: combining marks, variation selectors, skin tones, zero-width joiners, regional
indicator pairs, keycaps, and CRLF. The rest of the rules — Hangul syllables, Indic conjuncts —
are not what a roleplay composer meets.

.NET readers: ``StringInfo.GetNextTextElementLength``, by hand.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from typing import Final

ZWJ: Final = "‍"
VARIATION_SELECTORS: Final = frozenset({"︎", "️"})
KEYCAP: Final = "⃣"


def _modifier(c: str) -> bool:
    return "\U0001f3fb" <= c <= "\U0001f3ff"


def _regional(c: str) -> bool:
    return "\U0001f1e6" <= c <= "\U0001f1ff"


def _extends(c: str) -> bool:
    """Whether ``c`` continues the cluster before it."""
    return (
        unicodedata.category(c) in {"Mn", "Me", "Mc"}
        or c in VARIATION_SELECTORS
        or c in (KEYCAP, ZWJ)
        or _modifier(c)
    )


def cluster_length(text: str, start: int) -> int:
    """How many code points the cluster starting at ``start`` spans; at least one."""
    n = len(text)
    if start >= n:
        return 0
    i = start + 1
    if text[start] == "\r" and i < n and text[i] == "\n":
        return 2
    if _regional(text[start]) and i < n and _regional(text[i]):
        i += 1
    while i < n:
        c = text[i]
        if _extends(c):
            i += 1
            if c == ZWJ and i < n:
                i += 1  # the joiner takes the next character with it
            continue
        break
    return i - start


def clusters(text: str) -> Iterator[tuple[int, int]]:
    """Every cluster as ``(start, length)``."""
    at = 0
    while at < len(text):
        length = cluster_length(text, at)
        yield at, length
        at += length


def snap(text: str, index: int) -> int:
    """``index`` moved back to the start of the cluster it falls inside."""
    target = max(0, min(index, len(text)))
    if target in {0, len(text)}:
        return target
    at = 0
    while at < target:
        nxt = at + cluster_length(text, at)
        if nxt > target:
            return at
        at = nxt
    return target


def next_boundary(text: str, index: int) -> int:
    """The boundary after ``index``: one whole cluster to the right."""
    if index >= len(text):
        return len(text)
    start = snap(text, index)
    return min(len(text), start + cluster_length(text, start))


def previous_boundary(text: str, index: int) -> int:
    """The boundary before ``index``: one whole cluster to the left."""
    target = min(index, len(text))
    if target <= 0:
        return 0
    previous = 0
    at = 0
    while at < target:
        previous = at
        at += cluster_length(text, at)
    return previous
