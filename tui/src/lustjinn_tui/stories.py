"""The opening screen: the stories on the left, a preview of the selected one on the right
(``Views/ChatListView.cs``).

The list is read once on arrival and kept; ``R`` re-reads it. Filtering happens against the
held list on every keystroke, which is why ``/`` opens an inline field rather than a prompt —
the list narrows as you type without a round trip. A rename is edited in the same place, for the
same reason: it is one short string and a whole screen for it would be ceremony. Delete asks
first, naming the story, because there is no undo.

Three tenths of the width go to the list and the rest to the preview: names and ages are short,
a reply is prose and needs the room to be read at all.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import ClassVar, Literal, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Input, Static

from lustjinn_tui import prose
from lustjinn_tui.api import ApiError, Story, UnreachableError
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.fuzzy import rank
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.listing import Rows
from lustjinn_tui.newstory import NewStoryScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.textfmt import age, count, pad
from lustjinn_tui.theme import HEADING, HIGHLIGHT, SELECTION
from lustjinn_tui.view import View

AGE_WIDTH = 9
Mode = Literal["list", "filter", "rename"]


def moved_at(story: Story) -> datetime:
    """When the story last moved: its newest message, or its creation."""
    return story.last_message_at or story.created_at


def highlight(text: str, query: str) -> str:
    """``text`` as markup with every occurrence of ``query`` (case folded) in the highlight role
    (``Draw.Highlight``)."""
    if not query:
        return Content(text).markup
    parts: list[str] = []
    folded, needle = text.lower(), query.lower()
    at = 0
    while at < len(text):
        found = folded.find(needle, at)
        if found < 0:
            parts.append(Content(text[at:]).markup)
            break
        if found > at:
            parts.append(Content(text[at:found]).markup)
        parts.append(f"{HIGHLIGHT}{Content(text[found : found + len(query)]).markup}[/]")
        at = found + len(query)
    return "".join(parts)


class Preview(Widget):
    """The page beside the list: the selected story's name, who it is with, and its latest
    message drawn the way the transcript draws it — actions dimmed, quotation marks gone — so a
    reply is recognised at a glance. What does not fit is cut; reading is what opening is for."""

    def __init__(self) -> None:
        super().__init__()
        self._story: Story | None = None

    def show(self, story: Story | None) -> None:
        self._story = story
        self.refresh()

    def render(self) -> Content:
        story = self._story
        if story is None:
            return Content.from_markup("[$muted]Nothing selected.[/]")
        rule = Content.from_markup(f"[$border]{'─' * max(1, self.size.width - 2)}[/]")
        lines = [
            Content.from_markup(f"{HEADING}{Content(story.name).markup}[/]"),
            rule,
            Content.from_markup(f"[$accent]with {Content(story.character_name).markup}[/]"),
            Content(""),
            Content.from_markup("[$muted]Latest message[/]"),
            rule,
        ]
        latest = story.last_message_preview
        if not latest or not latest.strip():
            lines.append(
                Content.from_markup("[$muted]Nothing said yet — press Enter to open this story.[/]")
            )
        else:
            for n, paragraph in enumerate(prose.paragraphs(latest)):
                if n:
                    lines.append(Content(""))
                lines.append(prose.styled(paragraph))
        return Content("\n").join(lines)

    def on_resize(self) -> None:
        self.refresh()


class StoriesScreen(View):
    TITLE = "Stories"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Open the story"),
        Hint("N", "New story"),
        Hint("M", "Library"),
        Hint("F2", "Rename"),
        Hint("Del", "Delete story"),
        Hint("R", "Refresh"),
        Hint("/", "Filter"),
        Hint("Ctrl+F", "Search all"),
        Hint("Q", "Quit"),
    )
    FILTER_HINTS: ClassVar[tuple[Hint, ...]] = (Hint("Enter", "Apply"), Hint("Esc", "Clear filter"))
    # Nothing takes the focus on arrival: the keys are the screen's until / or F2 opens a field.
    AUTO_FOCUS: ClassVar[str | None] = ""
    RENAME_HINTS: ClassVar[tuple[Hint, ...]] = (Hint("Enter", "Rename"), Hint("Esc", "Cancel"))

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("enter,right", "open", "Open", show=False),
        Binding("n,N", "new_story", "New story", show=False),
        Binding("m,M", "library", "Library", show=False),
        Binding("f2", "rename", "Rename", show=False),
        Binding("delete", "delete", "Delete", show=False),
        Binding("r,R,ctrl+r", "refresh", "Refresh", show=False),
        Binding("slash", "filter", "Filter", show=False),
    ]

    DEFAULT_CSS = """
    StoriesScreen #split { height: 1fr; }
    StoriesScreen #pane { width: 30%; min-width: 28; height: 1fr; background: $surface; }
    StoriesScreen #pane Hairline { background: $surface; }
    StoriesScreen #header { height: 1; color: $muted; }
    StoriesScreen #pane Input { background: $surface; }
    StoriesScreen Preview { width: 1fr; height: 1fr; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._all: list[Story] = []
        self._query = ""
        self._mode: Mode = "list"

    # -- the frame ------------------------------------------------------------------------------

    def hints(self) -> tuple[Hint, ...]:
        if self._mode == "filter":
            return self.FILTER_HINTS
        if self._mode == "rename":
            return self.RENAME_HINTS
        return self.HINTS

    def summary(self) -> str | None:
        shown = len(self.rows.items)
        if self._query:
            return f"{shown} of {len(self._all)}"
        return count(shown, "story", "stories")

    def body(self) -> ComposeResult:
        with Horizontal(id="split"):
            with Vertical(id="pane"):
                yield Static("", id="header")
                yield Input(placeholder="type to filter…", id="filter", compact=True)
                yield Input(placeholder="new name…", id="rename", compact=True)
                yield Hairline()
                yield Rows[Story](self._row, empty="No stories yet. Press R to refresh.", id="list")
            yield Preview()

    def on_mount(self) -> None:
        self.query_one("#filter", Input).display = False
        self.query_one("#rename", Input).display = False
        self._show_header()

    def on_screen_resume(self) -> None:
        """Re-read whenever the screen comes back — a story just played has moved up — and
        the first time with a word on how many came. Not while the gate is still closed."""
        super().on_screen_resume()
        if not self.lustjinn.gate_open:
            return
        label = "Loading stories" if not self._all else None
        self.run_worker(partial(self._load, label), exclusive=True)

    @property
    def rows(self) -> Rows[Story]:
        return cast("Rows[Story]", self.query_one("#list", Rows))

    @property
    def selected(self) -> Story | None:
        return self.rows.selected

    # -- the list -------------------------------------------------------------------------------

    async def _load(self, label: str | None) -> None:
        """Re-reads the list, keeps the filter and the cursor, and with a ``label`` shows the
        spinner and then says how many came; without one it is quiet."""
        if label is None:
            try:
                listed = await self.lustjinn.api.stories()
            except ApiError, UnreachableError:
                return  # the next key the reader presses will meet the same answer, and say so
        else:
            listed = await self.lustjinn.call(label, self.lustjinn.api.stories())
            if listed is None:
                return
        self._all = listed
        self._apply_filter()
        if label is not None:
            self.status(f"{count(len(listed), 'story', 'stories')} loaded.", Kind.SUCCESS)

    def _apply_filter(self) -> None:
        visible = rank(self._all, self._query, lambda s: s.name)
        empty = (
            "No stories yet. Press R to refresh."
            if not self._all
            else "Nothing matches this filter. Press Esc to clear it."
        )
        self.rows.set_items(visible, empty=empty)
        self._show_header()
        self._show_preview()

    def _show_header(self) -> None:
        shown = len(self.rows.items)
        if self._query:
            text = f'{shown} of {len(self._all)} matching "{self._query}"'
        else:
            text = count(shown, "story", "stories")
        self.query_one("#header", Static).update(text)

    def _row(self, story: Story, selected: bool, width: int) -> Content:
        name_width = max(8, width - 3 - AGE_WIDTH - 1)
        name = pad(story.name, name_width)
        when = pad(age(moved_at(story)), AGE_WIDTH)
        if selected:
            line = Content(f"> {name} {when}").markup
            return Content.from_markup(f"{SELECTION}{line}[/]")
        return Content.from_markup(f"  {highlight(name, self._query)} [$muted]{when}[/]")

    @on(Rows.Selected)
    def _selection_moved(self) -> None:
        self._show_preview()

    @on(Rows.Opened)
    def _row_opened(self) -> None:
        self.action_open()

    # -- the preview ----------------------------------------------------------------------------

    def _show_preview(self) -> None:
        self.query_one(Preview).show(self.selected)

    # -- moving ---------------------------------------------------------------------------------

    def action_move(self, delta: int) -> None:
        self.rows.move(delta)

    def action_page(self, direction: int) -> None:
        self.rows.page(direction)

    def action_first(self) -> None:
        self.rows.first()

    def action_last(self) -> None:
        self.rows.last()

    # -- the keys -------------------------------------------------------------------------------

    def action_open(self) -> None:
        story = self.selected
        if story is not None and self._mode == "list":
            self.lustjinn.push_screen(ConversationScreen(story))

    def action_new_story(self) -> None:
        self.lustjinn.push_screen(NewStoryScreen())

    def action_library(self) -> None:
        self.status("The library is not here yet.")

    def action_refresh(self) -> None:
        self.run_worker(partial(self._load, "Refreshing"), exclusive=True)

    def action_back(self) -> None:
        """Esc clears a filter before it leaves the screen, as the donor's list did."""
        if self._mode == "filter":
            self._leave_filter(clear=True)
        elif self._mode == "rename":
            self._leave_rename()
            self.status("Rename cancelled.")
        elif self._query:
            self._query = ""
            self._apply_filter()
            self.status("Filter cleared.")
        else:
            self.lustjinn.go_back()

    # -- filtering ------------------------------------------------------------------------------

    def action_filter(self) -> None:
        if self._mode != "list":
            return
        self._mode = "filter"
        field = self.query_one("#filter", Input)
        field.value = self._query
        self.query_one("#header", Static).display = False
        field.display = True
        field.focus()
        self.refresh_hints()

    @on(Input.Changed, "#filter")
    def _filter_typed(self, event: Input.Changed) -> None:
        self._query = event.value
        self._apply_filter()

    @on(Input.Submitted, "#filter")
    def _filter_applied(self) -> None:
        self._leave_filter(clear=False)

    def _leave_filter(self, *, clear: bool) -> None:
        self._mode = "list"
        field = self.query_one("#filter", Input)
        field.display = False
        self.query_one("#header", Static).display = True
        self.set_focus(None)
        if clear:
            self._query = ""
            self._apply_filter()
            self.status("Filter cleared.")
        self.refresh_hints()

    # -- renaming -------------------------------------------------------------------------------

    def action_rename(self) -> None:
        story = self.selected
        if story is None or self._mode != "list":
            return
        self._mode = "rename"
        field = self.query_one("#rename", Input)
        field.value = story.name  # seeded, so a small correction does not mean retyping it
        self.query_one("#header", Static).display = False
        field.display = True
        field.focus()
        self.refresh_hints()
        self.status("Edit the name, then press Enter.")

    @on(Input.Submitted, "#rename")
    def _rename_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        story = self.selected
        self._leave_rename()
        if story is None:
            return
        if not name:
            self.status("A story needs a name. Nothing was changed.", Kind.WARNING)
            return
        if name == story.name:
            self.status("That is already its name.")
            return
        self.run_worker(partial(self._rename, story, name), exclusive=True)

    async def _rename(self, story: Story, name: str) -> None:
        renamed = await self.lustjinn.call(
            "Renaming", self.lustjinn.api.rename_story(story.id, name)
        )
        if renamed is None:
            return
        # Re-read so the row shows the name the server stored, and the held list stops
        # carrying the old one.
        listed = await self.lustjinn.call("Refreshing", self.lustjinn.api.stories())
        if listed is not None:
            self._all = listed
            self._apply_filter()
        self.status(f'Renamed to "{renamed.name}".', Kind.SUCCESS)

    def _leave_rename(self) -> None:
        self._mode = "list"
        field = self.query_one("#rename", Input)
        field.display = False
        field.value = ""
        self.query_one("#header", Static).display = True
        self.set_focus(None)
        self.refresh_hints()

    # -- deleting -------------------------------------------------------------------------------

    def action_delete(self) -> None:
        story = self.selected
        if story is None or self._mode != "list":
            return

        async def delete() -> None:
            await self.lustjinn.api.delete_story(story.id)
            self._all = await self.lustjinn.api.stories()
            self._apply_filter()
            self.status(f'Deleted "{story.name}".', Kind.SUCCESS)

        self.lustjinn.push_screen(
            ConfirmScreen(
                "Delete",
                f'Delete the story "{story.name}"?',
                (
                    "The whole story goes, every message in it, from the server itself.",
                    "This cannot be undone.",
                ),
                "Delete",
                delete,
            )
        )
