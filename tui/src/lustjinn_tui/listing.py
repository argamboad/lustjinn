"""Selection and scroll position for a vertical list (``Ui/ListState.cs``).

Every list-shaped screen needs exactly this, and getting the viewport arithmetic subtly wrong
in five places is how terminal UIs end up feeling broken. The offset keeps a margin of two rows
above and below the selection, so the cursor never sits flush against the edge while there is
more list to see.

.NET readers: a plain class with a few methods, no framework in it — the kind of thing xUnit
tests without a terminal. The Textual widget that draws it is ``Rows`` below.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final

from textual import events
from textual.content import Content
from textual.message import Message
from textual.widget import Widget

SCROLL_MARGIN: Final = 2


class ListState:
    def __init__(self) -> None:
        self._count = 0
        self._selected = 0
        self._offset = 0

    @property
    def count(self) -> int:
        return self._count

    @property
    def selected(self) -> int:
        """The selected index, or -1 when the list is empty."""
        return -1 if self._count == 0 else self._selected

    @property
    def offset(self) -> int:
        return self._offset

    def set_count(self, count: int) -> None:
        """A new count keeps the selection in range."""
        self._count = max(0, count)
        self._selected = min(max(self._selected, 0), max(0, self._count - 1))
        self._offset = min(max(self._offset, 0), max(0, self._count - 1))

    def move(self, delta: int) -> None:
        if self._count:
            self._selected = min(max(self._selected + delta, 0), self._count - 1)

    def select(self, index: int) -> None:
        if self._count:
            self._selected = min(max(index, 0), self._count - 1)

    def select_first(self) -> None:
        self._selected = 0

    def select_last(self) -> None:
        self._selected = max(0, self._count - 1)

    def viewport(self, height: int) -> tuple[int, int]:
        """Recomputes the offset for ``height`` rows: the first visible index and how many fit."""
        height = max(1, height)
        if self._count <= height:
            self._offset = 0
            return 0, self._count
        margin = min(SCROLL_MARGIN, (height - 1) // 2)
        if self._selected - margin < self._offset:
            self._offset = self._selected - margin
        elif self._selected + margin >= self._offset + height:
            self._offset = self._selected + margin - height + 1
        self._offset = min(max(self._offset, 0), self._count - height)
        return self._offset, height

    def index_at_row(self, row: int, height: int) -> int:
        """The index drawn on viewport row ``row``, or -1 past the end: for a click."""
        start, length = self.viewport(height)
        index = start + row
        return index if 0 <= row < length and index < self._count else -1


class Rows[T](Widget):
    """A list drawn one row per item through ``ListState``: the widget renders the rows that
    fit its height and nothing else, the way the donor's views did by hand. ``row`` draws one
    item; the widget posts ``Rows.Selected`` when the cursor moves and ``Rows.Opened`` on Enter
    or a second click, so the screen that owns it decides what those mean.

    .NET readers: a custom control with a ``SelectionChanged`` and an ``ItemActivated`` event;
    Textual's ``Message`` is the event, bubbled to the screen and handled by name.
    """

    DEFAULT_CSS = """
    Rows { height: 1fr; width: 1fr; }
    """

    class Selected(Message):
        def __init__(self, rows: Rows[Any], index: int) -> None:
            super().__init__()
            self.rows = rows
            self.index = index

        @property
        def control(self) -> Rows[Any]:
            return self.rows

    class Opened(Message):
        def __init__(self, rows: Rows[Any], index: int) -> None:
            super().__init__()
            self.rows = rows
            self.index = index

        @property
        def control(self) -> Rows[Any]:
            return self.rows

    def __init__(
        self,
        row: Callable[[T, bool, int], Content],
        *,
        empty: str = "Nothing here.",
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.state = ListState()
        self._items: Sequence[T] = ()
        self._row = row
        self._empty = empty

    # -- the items ----------------------------------------------------------------------------

    @property
    def items(self) -> Sequence[T]:
        return self._items

    def set_items(self, items: Sequence[T], *, empty: str | None = None) -> None:
        self._items = tuple(items)
        if empty is not None:
            self._empty = empty
        self.state.set_count(len(self._items))
        self.refresh()

    @property
    def selected(self) -> T | None:
        index = self.state.selected
        return self._items[index] if 0 <= index < len(self._items) else None

    # -- moving -------------------------------------------------------------------------------

    def move(self, delta: int) -> None:
        was = self.state.selected
        self.state.move(delta)
        self._moved(was)

    def page(self, direction: int) -> None:
        self.move(direction * max(1, self.size.height - 1))

    def first(self) -> None:
        was = self.state.selected
        self.state.select_first()
        self._moved(was)

    def last(self) -> None:
        was = self.state.selected
        self.state.select_last()
        self._moved(was)

    def select(self, index: int) -> None:
        was = self.state.selected
        self.state.select(index)
        self._moved(was)

    def _moved(self, was: int) -> None:
        self.refresh()
        if self.state.selected != was:
            self.post_message(self.Selected(self, self.state.selected))

    def open_selected(self) -> None:
        if self.selected is not None:
            self.post_message(self.Opened(self, self.state.selected))

    # -- drawing ------------------------------------------------------------------------------

    def render(self) -> Content:
        if not self._items:
            return Content.from_markup(f"[$muted]{Content(self._empty).markup}[/]")
        width = max(1, self.size.width)
        start, length = self.state.viewport(max(1, self.size.height))
        lines = [
            self._row(self._items[i], i == self.state.selected, width)
            for i in range(start, min(len(self._items), start + length))
        ]
        return Content("\n").join(lines)

    def on_resize(self) -> None:
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        index = self.state.index_at_row(event.y, max(1, self.size.height))
        if index < 0:
            return
        if index == self.state.selected:
            self.open_selected()
        else:
            self.select(index)
