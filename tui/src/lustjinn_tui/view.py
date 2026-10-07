"""The base screen every view extends: airp's ``View`` on Textual's ``Screen``.

A view declares a ``TITLE`` (the breadcrumb), its ``HINTS`` (the footer legend, in the donor's
order) and composes its body; the frame around it — masthead, legend, status row — is this
class's. ``Esc`` goes back one screen, and on the last one quits, as the donor's shell does.

.NET readers: this is ``Ui/View.cs`` and the parts of ``Ui/Shell.cs`` that drew around a view,
except that Textual owns the screen stack, the key dispatch and the redraw loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, cast

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen

from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import DEFAULT_HINTS, Hint, Legend
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.palette import HasCommands, PaletteCommand
from lustjinn_tui.status import Kind, StatusLine

if TYPE_CHECKING:
    from lustjinn_tui.app import LustjinnApp


class View(Screen[None], HasCommands):
    HINTS: ClassVar[tuple[Hint, ...]] = DEFAULT_HINTS

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

    def compose(self) -> ComposeResult:
        yield Masthead(badge=self.lustjinn.badge, model=self.lustjinn.model_name)
        with Vertical(id="body"):
            yield from self.body()
        yield Hairline()
        yield Legend()
        yield StatusLine()

    def body(self) -> ComposeResult:
        """The view's own widgets, between the masthead and the footer."""
        yield from ()

    # -- what the frame shows -----------------------------------------------------------------

    def hints(self) -> Sequence[Hint]:
        """The legend's hints right now; a view in a mode (filtering, renaming) overrides it."""
        return self.HINTS

    def summary(self) -> str | None:
        """A few cells beside the title on a narrow screen (``2/2``, ``5 stories``)."""
        return None

    def commands(self) -> list[PaletteCommand]:
        """What the palette lists for this screen, before the global commands."""
        return []

    def refresh_hints(self) -> None:
        self.query_one(Legend).hints = tuple(self.hints())

    def on_screen_resume(self) -> None:
        self.refresh_hints()
        self.query_one(Masthead).set_crumbs(self.lustjinn.crumbs())

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
