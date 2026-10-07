"""The base screen every view extends: airp's ``View`` on Textual's ``Screen``.

A view declares a ``TITLE`` (the breadcrumb), its ``HINTS`` (the footer legend, in the donor's
order) and composes its body; the frame around it — masthead, legend, status row — is this
class's. ``Esc`` goes back one screen, and on the last one quits, as the donor's shell does.

The frame follows the terminal's width live. Under sixty columns — a phone held upright, at a
font you can read — it changes shape: one row at the top (the title and where you are in it)
and one at the bottom (the legend, or the buttons with the mouse on, which a message borrows
for a few seconds), and changes back as soon as it is wider again. Over SSH this is the phone's
size, not the server's.

The keyboard dialect is applied here too: while nothing is being typed, a letter the Vim dialect
claims becomes the key it means before the screen's bindings see it.

.NET readers: this is ``Ui/View.cs`` and the parts of ``Ui/Shell.cs`` that drew around a view,
except that Textual owns the screen stack, the key dispatch and the redraw loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Final, cast

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Input, TextArea

from lustjinn_tui import buttons as phone
from lustjinn_tui.dialect import SWALLOW, translate
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import DEFAULT_HINTS, Hint, Legend, markup
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.palette import HasCommands, PaletteCommand
from lustjinn_tui.status import Kind, StatusLine

if TYPE_CHECKING:
    from lustjinn_tui.app import LustjinnApp

NARROW: Final = 60
"""Columns under which the screen is a phone's (``RenderContext.NarrowWidth``)."""


class View(Screen[None], HasCommands):
    HINTS: ClassVar[tuple[Hint, ...]] = DEFAULT_HINTS
    BUTTONS: ClassVar[tuple[phone.Button, ...]] = (phone.BACK,)

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", show=False),
        Binding("q,Q", "app.quit", "Quit", show=False),
        Binding("question_mark,f1", "app.help", "Help", show=False),
        Binding("ctrl+l", "clear_screen", "Clear", show=False),
    ]

    DEFAULT_CSS = """
    View { layout: vertical; }
    View > #body { height: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.narrow = False

    def compose(self) -> ComposeResult:
        yield Masthead(badge=self.lustjinn.badge, model=self.lustjinn.model_name)
        with Vertical(id="body"):
            yield from self.body()
        yield Hairline(id="footer-rule")
        yield Legend()
        yield StatusLine()

    def body(self) -> ComposeResult:
        """The view's own widgets, between the masthead and the footer."""
        yield from ()

    def on_mount(self) -> None:
        line = self.status_line
        line.legend = self._phone_legend
        if self.lustjinn.config.mouse:
            line.buttons = lambda: tuple(self.buttons())

    def _phone_legend(self) -> Content:
        """The legend fitted to the phone's one row, which is the status line's width."""
        return Content.from_markup(
            markup(tuple(self.hints()), max(20, self.status_line.size.width))
        )

    # -- what the frame shows -----------------------------------------------------------------

    def hints(self) -> Sequence[Hint]:
        """The legend's hints right now; a view in a mode (filtering, renaming) overrides it."""
        return self.HINTS

    def buttons(self) -> Sequence[phone.Button]:
        """The phone's bottom row with the mouse on: back, then what the screen does most."""
        return self.BUTTONS

    def summary(self) -> str | None:
        """A few cells beside the title on a narrow screen (``2/2``, ``5 stories``)."""
        return None

    def commands(self) -> list[PaletteCommand]:
        """What the palette lists for this screen, before the global commands."""
        return []

    def refresh_hints(self) -> None:
        self.query_one(Legend).hints = tuple(self.hints())
        self.status_line.refresh()
        self.refresh_summary()

    def refresh_summary(self) -> None:
        self.query_one(Masthead).set_crumbs(self.lustjinn.crumbs(), self.summary())

    def on_screen_resume(self) -> None:
        self.refresh_hints()
        self._fit_width()

    def on_resize(self) -> None:
        self._fit_width()

    def _fit_width(self) -> None:
        narrow = self.lustjinn.size.width < NARROW
        self.query_one(Masthead).set_narrow(narrow)
        if narrow == self.narrow:
            return
        self.narrow = narrow
        self.query_one("#footer-rule").display = not narrow
        self.query_one(Legend).display = not narrow
        self.status_line.set_narrow(narrow)
        self.refresh_summary()
        self.layout_changed(narrow)

    def layout_changed(self, narrow: bool) -> None:
        """The width crossed sixty columns, one way or the other: a view lays itself out again."""

    def legend_markup(self) -> str:
        return markup(tuple(self.hints()), max(20, self.size.width))

    # -- the dialect --------------------------------------------------------------------------

    @property
    def typing(self) -> bool:
        """Whether a text field has the focus: there every printable key types itself."""
        return isinstance(self.focused, Input | TextArea)

    def on_key(self, event: events.Key) -> None:
        if self.typing or event.character is None:
            return
        meant = translate(self.lustjinn.dialect, event.key)
        if meant is None:
            return
        event.stop()
        event.prevent_default()
        if meant != SWALLOW:
            self.lustjinn.post_message(events.Key(meant, None))

    # -- status -------------------------------------------------------------------------------

    def status(self, text: str, kind: Kind = Kind.INFO, hint: str = "") -> None:
        self.query_one(StatusLine).show(text, kind, hint)

    @property
    def status_line(self) -> StatusLine:
        return self.query_one(StatusLine)

    @property
    def legend(self) -> Legend:
        return self.query_one(Legend)

    @property
    def lustjinn(self) -> LustjinnApp:
        from lustjinn_tui.app import LustjinnApp

        # Textual types the property as App[object]; pyright loses the parameter.
        app = cast("App[Any]", self.app)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(app, LustjinnApp)
        return app

    # -- actions ------------------------------------------------------------------------------

    def action_back(self) -> None:
        self.lustjinn.go_back()

    def action_clear_screen(self) -> None:
        self.refresh(repaint=True)
        self.status("Screen cleared.")
