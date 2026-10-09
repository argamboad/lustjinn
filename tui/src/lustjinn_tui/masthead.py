"""The header: the app's name and a badge for the server; the breadcrumb of open screens and
the version under it; a rule (``Ui/Shell.cs``, ``BuildHeaderRows``). The donor showed the model
on the right; every story plays on the default here (#140), so there is nothing to show.

On a phone it is one row and its rule: what you are reading and where you are in it — the
screen's title and its summary — since a thirty-eight-column screen has no row to spare for a
brand."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.widgets import Static

from lustjinn_tui.hairline import Hairline
from lustjinn_tui.textfmt import fit
from lustjinn_tui.theme import BADGE, HEADING
from lustjinn_tui.version import short


class Masthead(Vertical):
    DEFAULT_CSS = """
    Masthead { height: auto; }
    Masthead Horizontal { height: 1; }
    Masthead .left { width: 1fr; }
    Masthead .right { width: auto; color: $muted; }
    """

    def __init__(self, *, badge: str = "Local") -> None:
        super().__init__()
        self._badge = badge
        self._crumbs: tuple[str, ...] = ()
        self._summary: str | None = None
        self.narrow = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="brand-row"):
            yield Static(self._brand(), classes="left", id="brand")
        with Horizontal():
            yield Static("", classes="left", id="crumbs")
            yield Static(short(), classes="right", id="version")
        yield Hairline()

    def _brand(self) -> Content:
        badge = Content(self._badge).markup
        return Content.from_markup(f"{HEADING}lustjinn[/]  {BADGE} {badge} [/]")

    def set_crumbs(self, titles: tuple[str, ...], summary: str | None = None) -> None:
        """The open screens' titles, earlier ones muted, joined by ``›``; on a phone the last
        title alone with the summary beside it."""
        self._crumbs = titles
        self._summary = summary
        self._draw_crumbs()

    def _draw_crumbs(self) -> None:
        titles = self._crumbs
        if self.narrow:
            title = Content(fit(titles[-1] if titles else "", max(8, self.size.width - 12))).markup
            summary = Content(self._summary or "").markup
            line = f"{HEADING}{title}[/]" + (f"  [$muted]{summary}[/]" if summary else "")
        elif titles:
            earlier = "".join(f"[$muted]{Content(t).markup} › [/]" for t in titles[:-1])
            line = earlier + Content(titles[-1]).markup
        else:
            line = ""
        self.query_one("#crumbs", Static).update(Content.from_markup(line))

    def set_narrow(self, narrow: bool) -> None:
        if narrow == self.narrow:
            return
        self.narrow = narrow
        self.query_one("#brand-row").display = not narrow
        self.query_one("#version").display = not narrow
        self._draw_crumbs()

    @property
    def crumbs(self) -> tuple[str, ...]:
        return self._crumbs
