"""The bottom row as buttons, on a phone with the mouse on (``Ui/Shell.cs``, ``PhoneBar``).

``‹`` is back, the ones beside it are what the screen does most, and ``⋯`` lists everything else
— the command palette. Every button is only a key the keyboard already has: a tap posts that key,
so a button can never do something the help does not list. Buttons are added from the left
until the row is full, ``⋯`` always keeps its place, and a tap between two buttons is nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from textual.content import Content

from lustjinn_tui.theme import KEY


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    key: str
    """The Textual key name a tap on it presses (``enter``, ``i``, ``alt+enter``)."""
    character: str | None = None
    """The character for a letter key, so the screen sees exactly what the keyboard sends."""


BACK = Button("‹", "escape")
MORE = Button("⋯", "ctrl+p")


def press(label: str, key: str) -> Button:
    """A button for a letter: its key name and the character the terminal would send."""
    return Button(label, key, key if len(key) == 1 else None)


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    button: Button


def fit(buttons: tuple[Button, ...], width: int) -> list[Button]:
    """The buttons that fit beside ``⋯``, from the left; the rest is what ``⋯`` is for."""
    reserve = 1 + cell_len(MORE.label) + 2
    kept: list[Button] = []
    used = 0
    for button in buttons:
        cost = cell_len(button.label) + 2 + (1 if kept else 0)
        if used + cost + reserve > width:
            break
        kept.append(button)
        used += cost
    kept.append(MORE)
    return kept


def bar(buttons: tuple[Button, ...], width: int) -> tuple[Content, list[Hit]]:
    """The row as key caps, and where each one is, for a tap."""
    parts: list[str] = []
    hits: list[Hit] = []
    column = 0
    for button in fit(buttons, width):
        if hits:
            parts.append(" ")
            column += 1
        cell = f" {button.label} "
        hits.append(Hit(column, column + cell_len(cell) - 1, button))
        parts.append(f"{KEY}{Content(cell).markup}[/]")
        column += cell_len(cell)
    return Content.from_markup("".join(parts)), hits


def tapped(hits: list[Hit], column: int) -> Button | None:
    return next((hit.button for hit in hits if hit.start <= column <= hit.end), None)
