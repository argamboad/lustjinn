"""The transcript: a story as a sequence of turns, not a wall of prose
(``Views/ConversationView.cs``).

The cursor moves between *turns*, not lines; each turn is labelled and coloured by who wrote it
and the selected one is marked down its left edge, so the reader always sees where they are in
a long scroll. Everything is wrapped to the measure, because replies run to thousands of
characters and truncating them loses exactly what the reader came for.

The rules the donor paid for, kept here:

- A turn is read from its beginning: opening a story, a reply arriving, a regenerate and a cut
  all land on the newest turn's *first* row (``land``).
- The viewport moves only when it has lost the selected turn altogether: paging inside a reply
  taller than the screen is never dragged back to its opening line (``_keep_visible``).
- ``↑``/``↓`` read on through a tall turn three rows at a time before moving to the neighbour,
  and enter the neighbour by the same step, so a swipe reads the transcript as one continuous
  thing (``step``).
- ``PgUp``/``PgDn`` scroll a screen and the selection follows the scroll; ``Home``/``End`` are
  the first and last turn.

The layout is pure (``layout``), so the tests pin it without a terminal. The widget is a Textual
``ScrollView``: it owns the scrollbar and the offset, and draws only the rows on screen.

.NET readers: a virtualised ``ItemsControl`` whose items are laid out by a pure function.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from rich.cells import cell_len
from textual.content import Content
from textual.geometry import Size
from textual.message import Message as TextualMessage
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.visual import RenderOptions

from lustjinn_tui import prose
from lustjinn_tui.api import Message
from lustjinn_tui.theme import CHIPS

READ_STEP: Final = 3
"""Rows one arrow moves through a turn taller than the screen. Three rather than a page: on a
phone a swipe arrives as a burst of arrows, one per line the finger travels."""

Marker = Literal["none", "speaker", "body"]


@dataclass(frozen=True, slots=True)
class Row:
    """One drawn row, the selection marker left off: the turn it belongs to (-1 for a separator
    between none), where its marker goes, and everything after the marker."""

    turn: int
    marker: Marker
    body: Content


@dataclass(frozen=True, slots=True)
class Pending:
    """A reply being written: what has arrived so far, drawn as the newest turn."""

    text: str


def label_of(role: str, speaker: str) -> str:
    if role == "user":
        return "You"
    if role == "assistant":
        return speaker
    return "Scene"


def _stamp(when: datetime) -> str:
    return when.astimezone().strftime("%a %H:%M")


def _speaker_row(turn: int, role: str, label: str, stamp: str, width: int) -> Row:
    """The speaker as a chip on the surface tone, the time at the far end of the measure."""
    chip = f" {label} "
    gap = max(1, width - cell_len(chip) - cell_len(stamp))
    chip_role = CHIPS.get(role, CHIPS["system"])
    markup = f"{chip_role}{Content(chip).markup}[/]{' ' * gap}[$muted]{Content(stamp).markup}[/]"
    return Row(turn, "speaker", Content.from_markup(markup))


def _body_rows(turn: int, text: str, width: int, query: str) -> list[Row]:
    rows: list[Row] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            rows.append(Row(turn, "body", Content("")))
            continue
        # Formatted before wrapping: the markers are removed first, so the widths the wrapper
        # measures are the widths drawn, and an action-heavy paragraph reaches the margin.
        styled = prose.styled(prose.runs(line), query)
        rows.extend(Row(turn, "body", piece) for piece in styled.wrap(width))
    return rows


def layout(
    messages: Sequence[Message],
    *,
    width: int,
    speaker: str,
    query: str = "",
    pending: Pending | None = None,
    rules: bool = True,
) -> list[Row]:
    """Every turn as the rows drawn: a speaker line, the wrapped body, a blank, and a hairline
    between turns (none on a phone, where the speaker's colour already divides them)."""
    rows: list[Row] = []
    width = max(1, width)
    count = len(messages) + (1 if pending is not None else 0)
    for i, message in enumerate(messages):
        label = label_of(message.role, speaker)
        rows.append(_speaker_row(i, message.role, label, _stamp(message.sent_at), width))
        rows.extend(_body_rows(i, message.text, width, query))
        rows.append(Row(i, "none", Content(" ")))
        if i < count - 1 and rules:
            rows.append(Row(i, "none", Content.from_markup(f"  [$border]{'─' * width}[/]")))
    if pending is not None:
        i = len(messages)
        rows.append(_speaker_row(i, "assistant", speaker, "", width))
        if pending.text:
            rows.extend(_body_rows(i, pending.text, width, ""))
        else:
            rows.append(Row(i, "body", Content.from_markup("[$muted]…[/]")))
        rows.append(Row(i, "none", Content(" ")))
    return rows


def first_row(rows: Sequence[Row], turn: int) -> int:
    return next((i for i, row in enumerate(rows) if row.turn == turn), -1)


def last_row(rows: Sequence[Row], turn: int) -> int:
    for i in range(len(rows) - 1, -1, -1):
        if rows[i].turn == turn:
            return i
    return -1


class Transcript(ScrollView):
    """The rows on screen, with the cursor's turn marked. Posts ``Moved`` when the cursor
    changes turn, so the header can say where the reader is."""

    DEFAULT_CSS = """
    Transcript { height: 1fr; width: 1fr; overflow-x: hidden; }
    """

    class Moved(TextualMessage):
        def __init__(self, transcript: Transcript) -> None:
            super().__init__()
            self.transcript = transcript

        @property
        def control(self) -> Transcript:
            return self.transcript

    def __init__(self, *, speaker: str, id: str | None = None) -> None:
        super().__init__(id=id)
        self.speaker = speaker
        self.messages: list[Message] = []
        self.search_query = ""
        self.pending: Pending | None = None
        self.rules = True
        self.selected = 0
        self._rows: list[Row] = []
        self._laid_out_width = 0
        self._pinned = False
        self._follow = False
        self._wanted: int | None = None

    # -- what is shown ----------------------------------------------------------------------

    @property
    def rows(self) -> list[Row]:
        return self._rows

    @property
    def turns(self) -> int:
        return len(self.messages) + (1 if self.pending is not None else 0)

    @property
    def selected_message(self) -> Message | None:
        if 0 <= self.selected < len(self.messages):
            return self.messages[self.selected]
        return None

    @property
    def measure(self) -> int:
        """Columns one line of prose gets: the width minus the marker, its space, a gap and
        the scrollbar."""
        return max(20, self.size.width - 4)

    def show(self, messages: Sequence[Message], *, land: bool = True) -> None:
        """New messages; ``land`` puts the cursor on the newest turn at its first row."""
        self.messages = list(messages)
        self.selected = min(self.selected, max(0, self.turns - 1))
        if land:
            self.land(self.turns - 1)
        else:
            self._relayout()

    def land(self, turn: int) -> None:
        """Selects ``turn`` and shows it from its first row on the next layout."""
        self.selected = max(0, min(turn, self.turns - 1))
        self._pinned = True
        self._relayout()
        self.post_message(self.Moved(self))

    def search(self, query: str) -> None:
        self.search_query = query
        self._relayout()

    def begin_pending(self) -> None:
        self.pending = Pending("")
        self._follow = True
        self._relayout()

    def grow_pending(self, piece: str) -> None:
        if self.pending is None:
            self.pending = Pending("")
        self.pending = Pending(self.pending.text + piece)
        self._relayout()

    def end_pending(self) -> None:
        self.pending = None
        self._follow = False
        self._relayout()

    # -- layout -------------------------------------------------------------------------------

    def _relayout(self) -> None:
        width = self.measure
        self._rows = layout(
            self.messages,
            width=width,
            speaker=self.speaker,
            query=self.search_query,
            pending=self.pending,
            rules=self.rules,
        )
        self._laid_out_width = width
        self.virtual_size = Size(1, len(self._rows))  # never wider than itself: no sideways bar
        if self._follow:
            self._scroll(max(0, len(self._rows) - self._available))
        elif self._pinned and self.size.height:
            self._pinned = False
            self._scroll(max(0, first_row(self._rows, self.selected)))
        else:
            self._keep_visible()
        self.refresh()

    def on_resize(self) -> None:
        if self.measure != self._laid_out_width:
            if self.size.height and not self._follow:
                self._pinned = True  # the rows moved under the cursor: find it again
            self._relayout()
        elif self._pinned:
            self._relayout()

    @property
    def _available(self) -> int:
        return max(1, self.scrollable_content_region.height)

    @property
    def top(self) -> int:
        """The first row on screen: what was last asked for, or where Textual is."""
        return self._wanted if self._wanted is not None else int(self.scroll_y)

    def _scroll(self, y: int) -> None:
        """Asks Textual to scroll once it has refreshed: a scroll asked for in the same breath
        as a new virtual size is clamped against the old one and lost."""
        self._wanted = max(0, y)
        self.call_after_refresh(self._apply_scroll)

    def _apply_scroll(self) -> None:
        if self._wanted is None:
            return
        wanted, self._wanted = self._wanted, None
        self.scroll_to(y=wanted, animate=False, immediate=True, force=True)

    def _keep_visible(self) -> None:
        """Moves the viewport only when it has lost the selected turn altogether."""
        first = first_row(self._rows, self.selected)
        if first < 0:
            return
        last = last_row(self._rows, self.selected)
        top = self.top
        available = self._available
        if last < top:
            self._scroll(first)
        elif first >= top + available:
            self._scroll(first if last - first >= available else last - available + 1)

    # -- moving -------------------------------------------------------------------------------

    def _select(self, turn: int) -> None:
        was = self.selected
        self.selected = max(0, min(turn, self.turns - 1))
        self.refresh()
        if self.selected != was:
            self.post_message(self.Moved(self))

    def step(self, direction: int) -> None:
        """Reads on through the selected turn while there is more of it off screen, and moves
        to the neighbour only when there is not."""
        if not self._rows:
            return
        first = first_row(self._rows, self.selected)
        last = last_row(self._rows, self.selected)
        if first < 0:
            self._select(self.selected + direction)
            return
        available = self._available
        top = max(0, min(self.top, len(self._rows) - available))
        bottom = top + available - 1
        if direction > 0:
            if last > bottom:
                self._scroll(min(top + READ_STEP, last - available + 1))
                return
            if self.selected < self.turns - 1:
                self._select(self.selected + 1)
                nxt = last + 1
                if nxt > bottom:
                    self._scroll(max(top, min(nxt - available + READ_STEP, nxt)))
            return
        if first < top:
            self._scroll(max(top - READ_STEP, first))
            return
        if self.selected > 0:
            self._select(self.selected - 1)
            previous = first - 1
            if previous < top:
                previous_first = first_row(self._rows, self.selected)
                self._scroll(max(previous_first, min(previous - READ_STEP + 1, top)))

    def page(self, direction: int) -> None:
        """A screenful, and the selection follows the scroll."""
        if not self._rows:
            return
        available = self._available
        top = self.top + direction * max(1, available - 1)
        top = max(0, min(top, len(self._rows) - available))
        self._scroll(top)
        self._select(self._rows[min(top, len(self._rows) - 1)].turn)

    def first(self) -> None:
        self._select(0)
        self._scroll(0)

    def last(self) -> None:
        self.land(self.turns - 1)

    # -- drawing ------------------------------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        index = y + int(self.scroll_y)
        if index < 0 or index >= len(self._rows):
            return Strip.blank(width, self.rich_style)
        row = self._rows[index]
        if row.marker == "none":
            content = row.body
        else:
            selected = row.turn == self.selected
            marker = "▌" if selected else " "
            prefix = marker if row.marker == "speaker" else marker + " "
            role = "$accent" if selected else "$border"
            content = Content.assemble((prefix, role), row.body)
        # The theme's variables ($accent, $muted…) resolve through the widget's own style
        # parser, the way Textual draws any widget's content.
        strips = content.render_strips(
            width,
            None,
            self.visual_style,
            RenderOptions(self._get_style, self.styles.get_rules()),  # pyright: ignore[reportPrivateUsage]
        )
        strip = strips[0] if strips else Strip.blank(width, self.rich_style)
        return strip.extend_cell_length(width, self.rich_style)
