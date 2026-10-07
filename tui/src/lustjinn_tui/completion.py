"""The composer's completion strip: what the caret could become, one row under the draft.

One row rather than a stacked list, because the composer is already competing with the story
for a small pane, and seven names cost seven rows of the transcript the message is a reply to.
Entries are measured in cells as they are added and dropped once the row is full; the hint keeps
its space, so the keys that drive the strip stay on screen; the highlighted entry is never
dropped — Tab has to be aimed at something the reader can see.

Keys the strip claims while it is open: ``Tab`` accepts, ``↑``/``↓`` choose, ``Esc`` dismisses
the list first and leaves the composer only on a second press. ``Enter`` is deliberately not
among them: it sends, it spends money, and a key that usually sends must not quietly mean
something else because a popup happens to be showing.

The offers come from *providers*: a command name after a slash (#50); emoji shortcodes,
snippets and words (#81).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from rich.cells import cell_len
from textual.content import Content
from textual.widget import Widget

from lustjinn_tui.theme import SELECTION

LIMIT = 7
"""How many completions are offered at once."""


@dataclass(frozen=True, slots=True)
class Completion:
    display: str
    """What the strip shows."""
    insert: str
    """What replaces the typed token when it is accepted."""


@dataclass(frozen=True, slots=True)
class Offer:
    """Completions for a span of the caret's line: where the token begins, how long it is, and
    what could replace it."""

    start: int
    length: int
    completions: tuple[Completion, ...]


Provider = Callable[[str, int, bool], Offer | None]
"""Given the caret's line, its column and whether it is the first line, an offer or none."""


class Strip(Widget):
    DEFAULT_CSS = """
    Strip { height: 1; width: 1fr; }
    """

    HINT: ClassVar[str] = "   Tab inserts · ↑↓ chooses · Esc dismisses"
    PHONE_HINT: ClassVar[str] = "   Tab inserts"

    def __init__(self) -> None:
        super().__init__()
        self.offer: Offer | None = None
        self.index = 0
        self.phone = False

    def show(self, offer: Offer | None) -> None:
        """A new offer resets the highlight to the top: a keystroke that reorders the list must
        not silently re-aim Tab at something else."""
        self.offer = offer
        self.index = 0
        self.display = offer is not None
        self.refresh()

    @property
    def chosen(self) -> Completion | None:
        if self.offer is None:
            return None
        return self.offer.completions[self.index]

    def move(self, delta: int) -> None:
        if self.offer is None:
            return
        self.index = (self.index + delta) % len(self.offer.completions)
        self.refresh()

    def render(self) -> Content:
        if self.offer is None:
            return Content("")
        hint = self.PHONE_HINT if self.phone else self.HINT
        budget = max(0, self.size.width - 2 - cell_len(hint))
        used = 0
        parts: list[str] = ["[$muted]  [/]"]
        for i, completion in enumerate(self.offer.completions):
            label = f" {completion.display} "
            cells = cell_len(label)
            if used + cells > budget and i != self.index:
                continue
            used += cells
            escaped = Content(label).markup
            parts.append(f"{SELECTION}{escaped}[/]" if i == self.index else f"[$muted]{escaped}[/]")
        parts.append(f"[$muted]{Content(hint).markup}[/]")
        return Content.from_markup("".join(parts))

    def on_resize(self) -> None:
        self.refresh()
