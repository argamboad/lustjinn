"""The colon tokens of the composer (``ShortcodeScanner.cs``): ``:name`` being typed opens the
picker, a closed ``:name:`` is an emoji, and a bare ``:name`` is a snippet trigger — the API
expands those when the message is stored, so a bare trigger is sent as typed.

A colon opens a word only after whitespace or at the start of the line: without that rule
every clock time and every URL in a message would pop the list open. A name is at most 32
characters of letters, digits, ``_``, ``+`` and ``-``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from lustjinn_tui import emoji

MAX_NAME: Final = 32


@dataclass(frozen=True, slots=True)
class Token:
    start: int
    """Where the colon is."""
    length: int
    """Through the caret."""
    query: str


def is_name_character(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c in "_+-")


def at(line: str, column: int) -> Token | None:
    """The ``:name`` being typed at ``column``, or None."""
    caret = max(0, min(column, len(line)))
    start = caret
    while start > 0 and is_name_character(line[start - 1]):
        start -= 1
    if start == 0 or line[start - 1] != ":":
        return None
    colon = start - 1
    if colon > 0 and not line[colon - 1].isspace():
        return None
    query = line[start:caret]
    if len(query) > MAX_NAME:
        return None
    return Token(colon, caret - colon, query)


def closed(line: str, column: int) -> tuple[Token, str] | None:
    """A fully typed ``:name:`` whose closing colon is just before the caret, with its emoji."""
    caret = max(0, min(column, len(line)))
    if caret == 0 or line[caret - 1] != ":":
        return None
    opened = at(line, caret - 1)
    if opened is None or not opened.query:
        return None
    found = emoji.find(opened.query)
    if found is None:
        return None
    return Token(opened.start, caret - opened.start, opened.query), found


def expand_all(text: str, snippet: Callable[[str], str | None]) -> str:
    """Every closed ``:name:`` replaced by its emoji and every bare ``:name`` by its snippet,
    wherever they open a word; clock times, URLs and unknown names exactly as typed."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        opens = text[i] == ":" and (i == 0 or text[i - 1].isspace())
        if not opens:
            out.append(text[i])
            i += 1
            continue
        end = i + 1
        while end < n and is_name_character(text[end]) and end - i <= MAX_NAME:
            end += 1
        name = text[i + 1 : end]
        if name and end < n and text[end] == ":":
            found = emoji.find(name)
            if found is not None:
                out.append(found)
                i = end + 1
                continue
        if name and (end == n or text[end] != ":"):
            expansion = snippet(name)
            if expansion:
                out.append(expansion)
                i = end
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def expand_emoji(text: str) -> str:
    """Only the emoji: what the composer sends, since the API expands the snippets itself."""
    return expand_all(text, lambda _: None)
