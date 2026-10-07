"""A reply as runs: narration, *action*, **emphasis** and "dialogue" — how a reply reads as a
scene rather than a wall of text. The rules are the donor's (``ProseFormat.cs``), the same port
the web app carries in ``prose.ts``:

- ``*…*`` is action and ``**…**`` is emphasis; a single run is never closed by the first half of
  a double marker, nor a double run by a lone asterisk inside it. A marker followed or preceded
  by whitespace is not a marker (``2 * 3``).
- ``"…"`` and ``“…”`` are dialogue, and must close on the same line.
- What the markers wrapped is kept; the markers themselves are not.

In the terminal, action and emphasis are both drawn in the ``action`` role (muted italic), as
the donor drew them; dialogue reads in the text colour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

from textual.content import Content

from lustjinn_tui.theme import ACTION, HIGHLIGHT

Kind = Literal["narration", "action", "emphasis", "dialogue"]


@dataclass(frozen=True, slots=True)
class Run:
    kind: Kind
    text: str


CLOSERS: Final[dict[str, str]] = {'"': '"', "“": "”"}


def _space(text: str, at: int) -> bool:
    return 0 <= at < len(text) and text[at].isspace()


def _closing_star(text: str, start: int, doubled: bool) -> int | None:
    if start >= len(text) or _space(text, start):
        return None
    i = start
    while i < len(text):
        if text[i] == "*" and (i + 1 < len(text) and text[i + 1] == "*") == doubled:
            return i if i > start and not _space(text, i - 1) else None
        i += 1
    return None


def _closing_quote(text: str, start: int, closer: str) -> int | None:
    if start >= len(text) or _space(text, start):
        return None
    close = text.find(closer, start)
    if close < 0 or close == start:
        return None
    return None if "\n" in text[start:close] else close  # dialogue does not span lines


def runs(text: str) -> list[Run]:
    """Splits one paragraph (or a whole reply) into runs. Adjacent narration is one run."""
    found: list[Run] = []
    plain: list[str] = []

    def flush() -> None:
        if plain:
            found.append(Run("narration", "".join(plain)))
            plain.clear()

    i = 0
    while i < len(text):
        here = text[i]
        if here == "*":
            doubled = i + 1 < len(text) and text[i + 1] == "*"
            marker = 2 if doubled else 1
            close = _closing_star(text, i + marker, doubled)
            if close is not None:
                flush()
                found.append(Run("emphasis" if doubled else "action", text[i + marker : close]))
                i = close + marker
                continue
        elif here in CLOSERS:
            close = _closing_quote(text, i + 1, CLOSERS[here])
            if close is not None:
                flush()
                found.append(Run("dialogue", text[i + 1 : close]))
                i = close + 1
                continue
        plain.append(here)
        i += 1
    flush()
    return found


def paragraphs(text: str) -> list[list[Run]]:
    """A reply as paragraphs of runs: blank lines divide paragraphs, as in the transcript."""
    blocks = re.split(r"\n{2,}", text.replace("\r\n", "\n"))
    return [runs(block.strip()) for block in blocks if block.strip()]


def plain(text: str) -> str:
    """The text with the markers removed: for a one-line preview."""
    return "".join(run.text for run in runs(text))


def painted(text: str, query: str) -> str:
    """The text as markup, every occurrence of ``query`` (case folded) in the highlight role, so
    an active search shows through whatever styling the run asked for."""
    if not query:
        return Content(text).markup
    parts: list[str] = []
    folded, needle = text.lower(), query.lower()
    at = 0
    while at < len(text):
        found = folded.find(needle, at)
        if found < 0:
            parts.append(Content(text[at:]).markup)
            break
        if found > at:
            parts.append(Content(text[at:found]).markup)
        parts.append(f"{HIGHLIGHT}{Content(text[found : found + len(query)]).markup}[/]")
        at = found + len(query)
    return "".join(parts)


def styled(found: list[Run], query: str = "") -> Content:
    """Runs as styled content: action and emphasis in the action role, the rest as they are,
    and a search ``query`` highlighted through both."""
    parts: list[str] = []
    for run in found:
        marked = painted(run.text, query)
        if run.kind in {"action", "emphasis"}:
            parts.append(f"{ACTION}{marked}[/]")
        else:
            parts.append(marked)
    return Content.from_markup("".join(parts))


def content(text: str) -> Content:
    """One paragraph as styled content."""
    return styled(runs(text))
