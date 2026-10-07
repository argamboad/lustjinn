"""The two keyboard dialects (``Ui/KeyMap.cs``): Standard, and Vim layered on top of it.

Vim adds ``h j k l``, ``G`` for the end, ``n``/``N`` for the next and previous match and ``u``
for undo — **only while navigating**. Inside any text field every printable key types itself,
so there is no mode to be in and none to leave. Arrow keys keep working, and every Ctrl chord
is the same in both. In Standard, ``n`` and ``N`` both find the next match, and ``G`` (or ``g``)
regenerates; in Vim ``G`` is the end of the transcript, so regenerate is ``Ctrl+G`` there — a
button has to mean the same thing whichever dialect is configured.

A dialect is a translation: the key the terminal sent becomes the key the screen's bindings
know. The screens bind the arrows and the chords once; the dialect decides what the letters
mean.
"""

from __future__ import annotations

from typing import Final, Literal

Dialect = Literal["standard", "vim"]

SWALLOW: Final = ""
"""The key means nothing in this dialect while navigating (Vim's ``g``, typed as a character)."""

VIM: Final[dict[str, str]] = {
    "h": "left",
    "j": "down",
    "k": "up",
    "l": "right",
    "G": "end",
    "g": SWALLOW,
    "u": "ctrl+z",
    # n and N are the screens' own bindings — next and previous — and stand as pressed.
}

STANDARD: Final[dict[str, str]] = {
    "N": "n",  # both find the next match
}


def translate(dialect: Dialect, key: str) -> str | None:
    """What ``key`` means while navigating: another key, ``SWALLOW``, or None when the dialect
    has nothing to say and the key stands as pressed."""
    table = VIM if dialect == "vim" else STANDARD
    return table.get(key)


def dialect_of(keyboard: str) -> Dialect:
    return "vim" if keyboard.strip().lower() == "vim" else "standard"
