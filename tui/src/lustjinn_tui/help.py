"""The help screen: every key, grouped by where it works (``Views/HelpView.cs``).

The rows are data, so the screen and the tests read the same table. Keys that a later issue adds
(the Vim dialect, the composer's helpers) extend ``SECTIONS`` when they land.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.content import Content
from textual.widgets import Static

from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.theme import HEADING
from lustjinn_tui.version import short
from lustjinn_tui.view import View

KEY_COLUMN: Final = 18


@dataclass(frozen=True, slots=True)
class Row:
    key: str
    description: str


@dataclass(frozen=True, slots=True)
class Section:
    name: str
    rows: tuple[Row, ...]


SECTIONS: Final[tuple[Section, ...]] = (
    Section(
        "Anywhere",
        (
            Row("Ctrl+P  or  :", "Command palette"),
            Row("Ctrl+F", "Search every story: names and messages"),
            Row("Ctrl+R  or  R", "Re-read from the server"),
            Row("Ctrl+L", "Clear and redraw the screen"),
            Row("F1  or  ?", "This help"),
            Row("Esc", "Back one screen"),
            Row("Ctrl+C  or  Q", "Quit"),
        ),
    ),
    Section(
        "Navigation",
        (
            Row("↑ ↓", "Move the selection"),
            Row("PgUp PgDn", "Move a page"),
            Row("Home End", "First / last item"),
            Row("Enter  or  →", "Open"),
            Row("Tab", "Next pane"),
        ),
    ),
    Section(
        "Stories",
        (
            Row("Enter", "Open the story"),
            Row("N", "New story"),
            Row("M", "Library"),
            Row("/", "Filter this list as you type"),
            Row("F2", "Rename the story"),
            Row("Del", "Delete the story, after confirming"),
        ),
    ),
    Section(
        "Conversation",
        (
            Row("I  or  Enter", "Write a message"),
            Row("PgUp PgDn", "Scroll the message being read"),
            Row("Home End", "First / last message"),
            Row(">", "Carry on with no prompt from you"),
            Row("G", "Regenerate the last reply"),
            Row("S", "Model and dials"),
            Row("B", "Branch from the selected message"),
            Row("Del", "Delete from the selected message onwards"),
            Row("/", "Search inside this story"),
            Row("C  /  X", "Copy the message / export the story"),
        ),
    ),
    Section(
        "Composer",
        (
            Row("Enter", "Send"),
            Row("/", "Start a command; Tab completes the name"),
            Row("/help", "Every command, with what each one costs"),
            Row("Alt+Enter", "New line"),
            Row("Ctrl+Z / Ctrl+Y", "Undo / redo"),
            Row("Esc", "Stop writing, keeping the draft"),
        ),
    ),
    Section(
        "Regenerate",
        (
            Row("↑ ↓", "Choose a reason"),
            Row("I", "Add instructions"),
            Row("Enter", "Regenerate"),
        ),
    ),
    Section(
        "Model and dials",
        (
            Row("↑ ↓  /  ← →", "Choose a setting / change its level"),
            Row("Enter", "Apply to the story"),
        ),
    ),
)


class HelpScreen(View):
    TITLE = "Help"
    HINTS: ClassVar[tuple[Hint, ...]] = (Hint("↑↓", "Scroll"), Hint("Esc", "Close"))
    AUTO_FOCUS: ClassVar[str | None] = "VerticalScroll"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "back", "Close", show=False),
    ]

    DEFAULT_CSS = """
    HelpScreen VerticalScroll { padding: 0 1; }
    HelpScreen .about { color: $muted; margin-bottom: 1; }
    HelpScreen .section { margin-top: 1; }
    HelpScreen .row { height: auto; }
    """

    def body(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(f"lustjinn {short()}", classes="about")
            for section in SECTIONS:
                yield Static(Content.from_markup(f"{HEADING}{section.name}[/]"), classes="section")
                yield Hairline()
                for row in section.rows:
                    yield Static(self._row(row), classes="row")

    @staticmethod
    def _row(row: Row) -> Content:
        key = Content(row.key.ljust(KEY_COLUMN)).markup
        return Content.from_markup(f"[$accent]{key}[/]{Content(row.description).markup}")
