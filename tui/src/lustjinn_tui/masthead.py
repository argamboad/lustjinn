"""The header: the app's name and a badge for the server, the model on the right; the breadcrumb
of open screens and the version under it; a rule (``Ui/Shell.cs``, ``BuildHeaderRows``)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.widgets import Static

from lustjinn_tui.hairline import Hairline
from lustjinn_tui.theme import BADGE, HEADING
from lustjinn_tui.version import short


class Masthead(Vertical):
    DEFAULT_CSS = """
    Masthead { height: 3; }
    Masthead Horizontal { height: 1; }
    Masthead .left { width: 1fr; }
    Masthead .right { width: auto; color: $muted; }
    """

    def __init__(self, *, badge: str = "Local", model: str = "") -> None:
        super().__init__()
        self._badge = badge
        self._model = model
        self._crumbs: tuple[str, ...] = ()

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self._brand(), classes="left", id="brand")
            yield Static(self._model, classes="right", id="model")
        with Horizontal():
            yield Static("", classes="left", id="crumbs")
            yield Static(short(), classes="right", id="version")
        yield Hairline()

    def _brand(self) -> Content:
        badge = Content(self._badge).markup
        return Content.from_markup(f"{HEADING}lustjinn[/]  {BADGE} {badge} [/]")

    def set_crumbs(self, titles: tuple[str, ...]) -> None:
        """The open screens' titles, earlier ones muted, joined by ``›``."""
        self._crumbs = titles
        if titles:
            earlier = "".join(f"[$muted]{Content(t).markup} › [/]" for t in titles[:-1])
            last = Content(titles[-1]).markup
        else:
            earlier, last = "", ""
        self.query_one("#crumbs", Static).update(Content.from_markup(earlier + last))

    def set_model(self, model: str) -> None:
        self._model = model
        self.query_one("#model", Static).update(model)

    @property
    def crumbs(self) -> tuple[str, ...]:
        return self._crumbs
