"""Search across every story: names and messages (``Views/SearchView.cs``).

A query, a scope stepped with ``Tab`` (everything, story names, messages), and the hits two
rows each — the story, what matched and who said it, then the snippet with the words lit.
``Enter`` searches, and once the hits are those of the query in the field, ``Enter`` opens the
selected story. The API does the finding (``GET /search``, #65) and ranks the hits.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import ClassVar, Literal, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.content import Content
from textual.widgets import Input, Static

from lustjinn_tui import prose
from lustjinn_tui.api import Hit
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.listing import Rows
from lustjinn_tui.status import Kind
from lustjinn_tui.textfmt import age, fit, pad
from lustjinn_tui.theme import HEADING, SELECTION
from lustjinn_tui.view import View

Scope = Literal["all", "names", "messages"]
SCOPES: tuple[Scope, ...] = ("all", "names", "messages")
DESCRIBED: dict[Scope, str] = {"all": "everything", "names": "story names", "messages": "messages"}


class SearchScreen(View):
    TITLE = "Search"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Search / open"),
        Hint("↑↓", "Move"),
        Hint("Tab", "Change scope"),
        Hint("Esc", "Back"),
    )
    AUTO_FOCUS: ClassVar[str | None] = "#query"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("tab", "scope", "Scope", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    SearchScreen #body { padding: 0 1; }
    SearchScreen #query-row { height: 1; margin-top: 1; }
    SearchScreen #where { height: 1; color: $muted; }
    """

    def __init__(self, query: str = "") -> None:
        super().__init__()
        self._initial = query
        self._scope: Scope = "all"
        self._searched = ""
        self._searched_scope: Scope = "all"
        self._hits: list[Hit] = []

    def body(self) -> ComposeResult:
        yield Input(self._initial, placeholder="search everything…", id="query", compact=True)
        yield Static("", id="where")
        yield Hairline()
        yield Rows[Hit](self._row, empty="Type a query and press Enter.", id="hits")

    def on_mount(self) -> None:
        self.rows.rows_per_item = 2
        self._show_where()

    @property
    def rows(self) -> Rows[Hit]:
        return cast("Rows[Hit]", self.query_one("#hits", Rows))

    @property
    def query_text(self) -> str:
        return self.query_one("#query", Input).value

    def _show_where(self) -> None:
        self.query_one("#where", Static).update(
            f"scope: {DESCRIBED[self._scope]}   ·   {len(self._hits)} result(s)"
        )

    def _row(self, hit: Hit, selected: bool, width: int) -> Content:
        """Two rows per hit: the story and what matched, then the snippet with the words lit."""
        marker = ">" if selected else " "
        what = "name" if hit.scope == "name" else "message"
        head = f"{marker} {pad(hit.story_name, 28)} {what}"
        if hit.speaker:
            head += f"  {hit.speaker}"
        if hit.sent_at:
            head += f"  {age(datetime.fromisoformat(hit.sent_at))}"
        head_markup = Content(fit(head, width)).markup
        first = f"{SELECTION}{head_markup}[/]" if selected else f"{HEADING}{head_markup}[/]"
        snippet = fit(prose.plain(hit.snippet), max(1, width - 4))
        second = f"    [$muted]{prose.painted(snippet, self._searched)}[/]"
        return Content.from_markup(f"{first}\n{second}")

    # -- the keys -------------------------------------------------------------------------------

    def action_scope(self) -> None:
        self._scope = SCOPES[(SCOPES.index(self._scope) + 1) % len(SCOPES)]
        self._show_where()
        self.status(f"Scope: {DESCRIBED[self._scope]}")

    def action_move(self, delta: int) -> None:
        self.rows.move(delta)

    def action_page(self, direction: int) -> None:
        self.rows.page(direction)

    @on(Input.Submitted, "#query")
    def _entered(self, event: Input.Submitted) -> None:
        same = event.value == self._searched and self._scope == self._searched_scope
        if self._hits and same:
            self._open()
        else:
            self.run_worker(partial(self._search, event.value), exclusive=True)

    @on(Rows.Opened)
    def _row_opened(self) -> None:
        self._open()

    async def _search(self, query: str) -> None:
        if not query.strip():
            self.status("Type something to search for.", Kind.WARNING)
            return
        results = await self.lustjinn.call(
            f'Searching for "{query}"', self.lustjinn.api.search(query.strip())
        )
        if results is None:
            return
        hits = results.hits
        if self._scope == "names":
            hits = [h for h in hits if h.scope == "name"]
        elif self._scope == "messages":
            hits = [h for h in hits if h.scope == "message"]
        self._searched = query
        self._searched_scope = self._scope
        self._hits = hits
        self.rows.set_items(hits, empty=f'Nothing matches "{query}".')
        self.rows.first()
        self._show_where()
        if hits:
            self.status(f"{len(hits)} result(s) in {results.searched} story(ies).", Kind.SUCCESS)
        else:
            self.status(f'Nothing matches "{query}".', Kind.WARNING)

    def _open(self) -> None:
        hit = self.rows.selected
        if hit is None:
            return
        self.run_worker(partial(self._open_story, hit), exclusive=True)

    async def _open_story(self, hit: Hit) -> None:
        story = await self.lustjinn.call("Opening", self.lustjinn.api.story(hit.story_id))
        if story is not None:
            self.lustjinn.push_screen(ConversationScreen(story))
