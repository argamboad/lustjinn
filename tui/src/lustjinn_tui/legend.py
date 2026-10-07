"""The footer's key legend: the current screen's keys, fitted to the width.

The donor's rule (``Ui/Shell.cs``, ``Legend``): hints are added in order; a hint costs the cells
of its key, its label and four more (the cap's two spaces and the two-space separator). Every hint
but the last must leave room for the pointer ``? All keys`` (13 cells); the last only has to fit
the width. The first hint that does not fit stops the loop and drops everything after it, and
the pointer is then appended, so the reader always knows there is more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rich.cells import cell_len
from textual.content import Content
from textual.reactive import reactive
from textual.widget import Widget

from lustjinn_tui.theme import KEY

HINT_PADDING: Final = 4


@dataclass(frozen=True, slots=True)
class Hint:
    """One key and what it does, as the legend shows them: ``Enter`` ``Open the story``."""

    key: str
    label: str

    def cost(self) -> int:
        return cell_len(self.key) + cell_len(self.label) + HINT_PADDING


ALL_KEYS: Final = Hint("?", "All keys")
RESERVE: Final = ALL_KEYS.cost()  # 13

DEFAULT_HINTS: Final[tuple[Hint, ...]] = (
    Hint("Enter", "Open"),
    Hint("Esc", "Back"),
    Hint("Ctrl+P", "Commands"),
    Hint("F1", "Help"),
    Hint("Q", "Quit"),
)


def fit(hints: tuple[Hint, ...], width: int) -> tuple[tuple[Hint, ...], bool]:
    """The hints that fit in ``width`` cells, and whether any were dropped."""
    kept: list[Hint] = []
    used = 0
    dropped = False
    last = len(hints) - 1
    for i, hint in enumerate(hints):
        limit = width if i == last else width - RESERVE
        if used + hint.cost() > limit:
            dropped = True
            break
        kept.append(hint)
        used += hint.cost()
    return tuple(kept), dropped


def markup(hints: tuple[Hint, ...], width: int) -> str:
    kept, dropped = fit(hints, width)
    shown = [*kept, ALL_KEYS] if dropped else list(kept)
    return "  ".join(f"{KEY} {h.key} [/][$muted]{h.label}[/]" for h in shown)


class Legend(Widget):
    """One row: the fitted hints, re-fitted whenever the width changes."""

    DEFAULT_CSS = """
    Legend { height: 1; width: 1fr; }
    """

    hints: reactive[tuple[Hint, ...]] = reactive(DEFAULT_HINTS, layout=False)

    def render(self) -> Content:
        return Content.from_markup(markup(self.hints, max(20, self.size.width)))

    def on_resize(self) -> None:
        self.refresh()

    @property
    def text(self) -> str:
        """What the reader sees, as plain text: for the tests."""
        return self.render().plain
