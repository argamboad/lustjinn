"""The footer's status row: a message that stays until something replaces it, or the spinner
while work runs (``Ui/Shell.cs``, footer row 3).

On a desk the donor keeps the message until the next status, the next run or the next error; it
never times out. The spinner advances every 90 ms with ``{label}…  Esc to stop`` beside it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from textual.content import Content
from textual.timer import Timer
from textual.widget import Widget

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

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._kind = Kind.INFO
        self._hint = ""
        self._busy: str | None = None
        self._frame = 0
        self._timer: Timer | None = None

    # -- messages -----------------------------------------------------------------------------

    def show(self, text: str, kind: Kind = Kind.INFO, hint: str = "") -> None:
        """A message, coloured by kind; an error may carry a recovery hint after it."""
        self._text, self._kind, self._hint = text, kind, hint
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
        if self._busy is not None:
            frame = FRAMES[self._frame]
            label = Content(self._busy).markup
            return Content.from_markup(
                f"[$accent]{frame}[/] [$foreground]{label}…[/]  [$muted]Esc to stop[/]"
            )
        if not self._text:
            return Content("")
        line = f"[{STYLE[self._kind]}]{Content(self._text).markup}[/]"
        if self._hint:
            line += f"  [$muted]{Content(self._hint).markup}[/]"
        return Content.from_markup(line)
