"""The footer's status row: a message that stays until something replaces it, or the spinner
while work runs (``Ui/Shell.cs``, footer row 3).

On a desk the donor keeps the message until the next status, the next run or the next error; it
never times out. The spinner advances every 90 ms with ``{label}…  Esc to stop`` beside it.

On a phone this is the only footer row: the legend's hints (or the buttons, with the mouse on)
stand here while nothing else needs saying, a message takes the row for a few seconds, and the
spinner takes it for as long as the work runs.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, ClassVar, Final, cast

from textual import events
from textual.app import App
from textual.content import Content
from textual.timer import Timer
from textual.widget import Widget

from lustjinn_tui import buttons as phone

FRAMES: Final = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
FRAME_SECONDS: Final = 0.09


class Kind(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


STYLE: Final[dict[Kind, str]] = {
    Kind.INFO: "$muted",
    Kind.SUCCESS: "$success",
    Kind.WARNING: "$warning",
    Kind.ERROR: "$error",
}


class StatusLine(Widget):
    DEFAULT_CSS = """
    StatusLine { height: 1; width: 1fr; }
    """

    LINGER_SECONDS: ClassVar[float] = 4.0
    """How long a message holds the phone's one row before the legend comes back."""

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._kind = Kind.INFO
        self._hint = ""
        self._busy: str | None = None
        self._frame = 0
        self._timer: Timer | None = None
        self.narrow = False
        self.legend: Callable[[], Content] | None = None
        """What the row shows on a phone while idle: the legend's markup."""
        self.buttons: Callable[[], tuple[phone.Button, ...]] | None = None
        """The buttons instead, when the mouse is on."""
        self._hits: list[phone.Hit] = []
        self._shown_at = 0
        self._expiry: Timer | None = None

    # -- messages -----------------------------------------------------------------------------

    def show(self, text: str, kind: Kind = Kind.INFO, hint: str = "") -> None:
        """A message, coloured by kind; an error may carry a recovery hint after it. On a phone
        it holds the row for a few seconds, then the legend comes back."""
        self._text, self._kind, self._hint = text, kind, hint
        self._shown_at += 1
        if self._expiry is not None:
            self._expiry.stop()
            self._expiry = None
        if self.narrow and text:
            stamp = self._shown_at
            self._expiry = self.set_timer(self.LINGER_SECONDS, lambda: self._expire(stamp))
        self.refresh()

    def set_narrow(self, narrow: bool) -> None:
        """A message already on the row when the screen turns narrow lingers like any other."""
        self.narrow = narrow
        if narrow and self._text and self._expiry is None:
            stamp = self._shown_at
            self._expiry = self.set_timer(self.LINGER_SECONDS, lambda: self._expire(stamp))
        self.refresh()

    def _expire(self, stamp: int) -> None:
        if stamp == self._shown_at and self.narrow:
            self._text = ""
            self.refresh()

    def clear(self) -> None:
        self.show("")

    @property
    def text(self) -> str:
        return self._text

    @property
    def kind(self) -> Kind:
        return self._kind

    # -- busy ---------------------------------------------------------------------------------

    def busy(self, label: str) -> None:
        """Show the spinner with ``label``; clears any message, as the donor's Run does."""
        self._text = ""
        self._busy = label
        self._frame = 0
        if self._timer is None:
            self._timer = self.set_interval(FRAME_SECONDS, self._tick)
        self.refresh()

    def idle(self) -> None:
        self._busy = None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.refresh()

    @property
    def is_busy(self) -> bool:
        return self._busy is not None

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(FRAMES)
        self.refresh()

    # -- render -------------------------------------------------------------------------------

    def render(self) -> Content:
        self._hits = []
        if self._busy is not None:
            frame = FRAMES[self._frame]
            label = Content(self._busy).markup
            return Content.from_markup(
                f"[$accent]{frame}[/] [$foreground]{label}…[/]  [$muted]Esc to stop[/]"
            )
        if not self._text:
            return self._idle_row()
        line = f"[{STYLE[self._kind]}]{Content(self._text).markup}[/]"
        if self._hint:
            line += f"  [$muted]{Content(self._hint).markup}[/]"
        return Content.from_markup(line)

    def _idle_row(self) -> Content:
        """Nothing to say: on a phone, the legend or the buttons; on a desk, nothing."""
        if not self.narrow:
            return Content("")
        if self.buttons is not None:
            content, self._hits = phone.bar(self.buttons(), max(10, self.size.width))
            return content
        if self.legend is not None:
            return self.legend()
        return Content("")

    def on_click(self, event: events.Click) -> None:
        """A tap on a button presses its key — nothing a tap can do is not also a key."""
        button = phone.tapped(self._hits, event.x)
        if button is not None:
            app = cast("App[Any]", self.app)  # pyright: ignore[reportUnknownMemberType]
            app.post_message(events.Key(button.key, button.character))

    def on_resize(self) -> None:
        self.refresh()
