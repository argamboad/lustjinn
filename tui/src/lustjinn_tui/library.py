"""The library: characters, personas and snippets, read and kept from the terminal
(``Views/LibraryView.cs``).

Three shelves across the top, the names down the left, the text on the right. ``N`` names a
new entry and opens it in the editor with a skeleton to fill in; ``Enter`` edits the text,
``O`` a character's opening, ``F2`` renames, ``Del`` removes after asking (the server refuses
while a live story uses it, and says which); ``D`` makes a persona the default.

A save carries the version the editor started from. When the entry moved on in between —
edited on the phone while the laptop had it open — the API refuses with the entry as it is now,
and ``ConflictScreen`` shows that text so the reader decides: ``Enter`` saves theirs over it,
``Esc`` keeps the server's and drops theirs. Nothing is overwritten by accident.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import ClassVar, Literal, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Input, Static

from lustjinn_tui import skeletons
from lustjinn_tui.api import ApiError, ConflictError, Entry, EntryFull, Shelf, UnreachableError
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.editor import editor_name
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.listing import Rows
from lustjinn_tui.status import Kind
from lustjinn_tui.textfmt import count, pad
from lustjinn_tui.theme import HEADING, SELECTION
from lustjinn_tui.view import View

SHELVES: tuple[Shelf, ...] = ("characters", "personas", "snippets")
KINDS: dict[Shelf, str] = {"characters": "character", "personas": "persona", "snippets": "snippet"}
Mode = Literal["list", "naming", "renaming"]


class ConflictScreen(View):
    """The entry as the server has it now, beside what the reader was about to save."""

    TITLE = "Changed elsewhere"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Save mine over it"),
        Hint("PgUp/PgDn", "Read theirs"),
        Hint("Esc", "Keep theirs"),
    )
    AUTO_FOCUS: ClassVar[str | None] = ""
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "save_mine", "Save mine", show=False),
        Binding("pageup", "page(-1)", "Up", show=False),
        Binding("pagedown", "page(1)", "Down", show=False),
    ]

    DEFAULT_CSS = """
    ConflictScreen #body { padding: 0 2; }
    ConflictScreen .heading { margin-top: 1; }
    ConflictScreen .why { color: $warning; }
    ConflictScreen VerticalScroll { height: 1fr; }
    ConflictScreen .theirs { padding-left: 2; color: $muted; }
    """

    def __init__(
        self, message: str, theirs: EntryFull, save: Callable[[EntryFull], Awaitable[object]]
    ) -> None:
        super().__init__()
        self.theirs = theirs
        self._message = message
        self._save = save

    def body(self) -> ComposeResult:
        yield Static(
            Content.from_markup(
                f"{HEADING}{Content(self.theirs.name).markup}[/]   "
                f"[$muted]version {self.theirs.version}, as the server has it now[/]"
            ),
            classes="heading",
        )
        yield Static(self._message, classes="why")
        yield Hairline()
        with VerticalScroll():
            yield Static(self.theirs.text, classes="theirs")

    def action_page(self, direction: int) -> None:
        scroller = self.query_one(VerticalScroll)
        if direction > 0:
            scroller.scroll_page_down(animate=False)
        else:
            scroller.scroll_page_up(animate=False)

    async def action_save_mine(self) -> None:
        app = self.lustjinn
        app.pop_screen()
        await app.call("Saving", self._save(self.theirs))

    def action_back(self) -> None:
        below = self.lustjinn.screen_stack[-2]
        self.lustjinn.pop_screen()
        if isinstance(below, View):
            below.status("Kept the server's text. Yours was not saved.", Kind.WARNING)


class LibraryScreen(View):
    TITLE = "Library"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("←→", "Shelf"),
        Hint("Enter", "Edit"),
        Hint("N", "New"),
        Hint("O", "Opening"),
        Hint("F2", "Rename"),
        Hint("D", "Default persona"),
        Hint("Del", "Remove"),
        Hint("PgUp/PgDn", "Read"),
        Hint("Esc", "Back"),
    )
    NAMING_HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Create and edit"),
        Hint("Esc", "Cancel"),
    )
    RENAMING_HINTS: ClassVar[tuple[Hint, ...]] = (Hint("Enter", "Rename"), Hint("Esc", "Cancel"))
    AUTO_FOCUS: ClassVar[str | None] = ""
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "shelf(-1)", "Previous shelf", show=False),
        Binding("right,tab", "shelf(1)", "Next shelf", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("pageup", "page(-1)", "Read up", show=False),
        Binding("pagedown", "page(1)", "Read down", show=False),
        Binding("n,N", "new", "New", show=False),
        Binding("enter", "edit", "Edit", show=False),
        Binding("o,O", "opening", "Opening", show=False),
        Binding("f2", "rename", "Rename", show=False),
        Binding("d,D", "default", "Default persona", show=False),
        Binding("delete", "remove", "Remove", show=False),
        Binding("r,R,ctrl+r", "refresh", "Refresh", show=False),
    ]

    DEFAULT_CSS = """
    LibraryScreen #tabs { height: 1; padding: 0 1; }
    LibraryScreen #split { height: 1fr; }
    LibraryScreen #pane { width: 30%; min-width: 16; height: 1fr; background: $surface; }
    LibraryScreen #pane Input { background: $surface; }
    LibraryScreen #text { width: 1fr; height: 1fr; padding: 0 1; }
    LibraryScreen #text VerticalScroll { height: 1fr; }
    LibraryScreen .caption { color: $muted; height: 1; }
    LibraryScreen .prose { color: $muted; }
    """

    def __init__(self, shelf: Shelf = "characters") -> None:
        super().__init__()
        self.shelf: Shelf = shelf
        self._mode: Mode = "list"
        self._default_persona: uuid.UUID | None = None
        self._shown: EntryFull | None = None

    # -- the frame ------------------------------------------------------------------------------

    def hints(self) -> tuple[Hint, ...]:
        if self._mode == "naming":
            return self.NAMING_HINTS
        if self._mode == "renaming":
            return self.RENAMING_HINTS
        return self.HINTS

    def summary(self) -> str | None:
        return count(len(self.rows.items), KINDS[self.shelf])

    def body(self) -> ComposeResult:
        yield Static("", id="tabs")
        yield Hairline()
        with Horizontal(id="split"):
            with Vertical(id="pane"):
                yield Input(placeholder="name…", id="name", compact=True)
                yield Rows[Entry](self._row, empty="", id="list")
            with Vertical(id="text"):
                yield Static("", classes="caption", id="caption")
                with VerticalScroll():
                    yield Static("", classes="prose", id="prose")

    def on_mount(self) -> None:
        self.query_one("#name", Input).display = False
        self._show_tabs()
        self.run_worker(partial(self._load, True), exclusive=True)

    @property
    def rows(self) -> Rows[Entry]:
        return cast("Rows[Entry]", self.query_one("#list", Rows))

    @property
    def selected(self) -> Entry | None:
        return self.rows.selected

    @property
    def kind(self) -> str:
        return KINDS[self.shelf]

    # -- loading --------------------------------------------------------------------------------

    async def _load(self, announce: bool, *, select: uuid.UUID | None = None) -> None:
        api = self.lustjinn.api
        listed = await self.lustjinn.call(f"Reading the {self.shelf}", api.entries(self.shelf))
        if listed is None:
            return
        if self.shelf == "personas":
            defaults = await self.lustjinn.call("Reading the default", api.defaults())
            self._default_persona = defaults.default_persona_id if defaults else None
        self.rows.set_items(listed, empty=f"No {self.kind}s yet — N starts one.")
        if select is not None:
            index = next((i for i, e in enumerate(listed) if e.id == select), -1)
            if index >= 0:
                self.rows.select(index)
        self._show_tabs()
        await self._show_text()
        if announce:
            self.status(f"{count(len(listed), self.kind)} on the shelf.", Kind.SUCCESS)

    def _show_tabs(self) -> None:
        parts: list[str] = []
        for shelf in SHELVES:
            label = Content(f" {shelf.capitalize()} ").markup
            parts.append(f"{SELECTION}{label}[/]" if shelf == self.shelf else f"[$muted]{label}[/]")
        self.query_one("#tabs", Static).update(Content.from_markup("  ".join(parts)))

    def _row(self, entry: Entry, selected: bool, width: int) -> Content:
        marker = "★ " if self.shelf == "personas" and entry.id == self._default_persona else "  "
        line = Content(pad(f"{marker}{entry.name}", width)).markup
        return Content.from_markup(f"{SELECTION}{line}[/]" if selected else line)

    async def _show_text(self) -> None:
        entry = self.selected
        caption = self.query_one("#caption", Static)
        prose = self.query_one("#prose", Static)
        if entry is None:
            self._shown = None
            caption.update("")
            prose.update("")
            return
        try:
            full = await self.lustjinn.api.entry(self.shelf, entry.id)
        except ApiError, UnreachableError:
            return
        self._shown = full
        used = f"used by {', '.join(full.used_by)}" if full.used_by else "used by no live story"
        if self.shelf == "snippets":
            used = "copied into a message when :name is typed"
        caption.update(f"{full.name}   ·   version {full.version}   ·   {used}")
        text = full.text
        if self.shelf == "characters":
            opening = full.opening.strip() if full.opening else "(none — O writes one)"
            text += f"\n\n=== THE OPENING ===\n\n{opening}"
        prose.update(text)
        self.query_one(VerticalScroll).scroll_home(animate=False)

    @on(Rows.Selected)
    async def _selection_moved(self) -> None:
        await self._show_text()

    @on(Rows.Opened)
    def _row_opened(self) -> None:
        self.action_edit()

    # -- moving ---------------------------------------------------------------------------------

    def action_shelf(self, delta: int) -> None:
        if self._mode != "list":
            return
        at = SHELVES.index(self.shelf)
        self.shelf = SHELVES[(at + delta) % len(SHELVES)]
        self.rows.set_items(())
        self.run_worker(partial(self._load, False), exclusive=True)

    def action_move(self, delta: int) -> None:
        self.rows.move(delta)

    def action_first(self) -> None:
        self.rows.first()

    def action_last(self) -> None:
        self.rows.last()

    def action_page(self, direction: int) -> None:
        scroller = self.query_one(VerticalScroll)
        if direction > 0:
            scroller.scroll_page_down(animate=False)
        else:
            scroller.scroll_page_up(animate=False)

    def action_refresh(self) -> None:
        self.run_worker(partial(self._load, True), exclusive=True)

    def action_back(self) -> None:
        if self._mode != "list":
            self._leave_field()
            self.status("Cancelled.")
            return
        self.lustjinn.go_back()

    # -- naming and renaming --------------------------------------------------------------------

    def _open_field(self, mode: Mode, value: str, placeholder: str) -> None:
        self._mode = mode
        field = self.query_one("#name", Input)
        field.value = value
        field.placeholder = placeholder
        field.display = True
        field.focus()
        self.refresh_hints()

    def _leave_field(self) -> None:
        self._mode = "list"
        field = self.query_one("#name", Input)
        field.display = False
        field.value = ""
        self.set_focus(None)
        self.refresh_hints()

    def action_new(self) -> None:
        if self._mode == "list":
            self._open_field("naming", "", f"new {self.kind}: its name")

    def action_rename(self) -> None:
        entry = self.selected
        if self._mode == "list" and entry is not None:
            self._open_field("renaming", entry.name, "new name")

    @on(Input.Submitted, "#name")
    def _named(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        mode = self._mode
        entry = self.selected
        self._leave_field()
        if not name:
            self.status(f"A {self.kind} needs a name.", Kind.WARNING)
            return
        if mode == "naming":
            self.run_worker(partial(self._create, name), exclusive=True)
        elif entry is not None:
            if name == entry.name:
                self.status("That is already its name.")
                return
            self.run_worker(partial(self._rename, entry, name), exclusive=True)

    async def _create(self, name: str) -> None:
        created = await self.lustjinn.call(
            "Creating",
            self.lustjinn.api.create_entry(self.shelf, name, skeletons.BY_SHELF[self.shelf]),
        )
        if created is None:
            return
        await self._load(False, select=created.id)
        await self._edit(created, "text")

    async def _rename(self, entry: Entry, name: str) -> None:
        renamed = await self._save(entry.id, entry.version, name=name)
        if renamed is not None:
            await self._load(False, select=renamed.id)
            self.status(
                f'Renamed to "{renamed.name}". Every story using it sees the name at once.',
                Kind.SUCCESS,
            )

    # -- editing --------------------------------------------------------------------------------

    def action_edit(self) -> None:
        entry = self._shown
        if self._mode != "list" or entry is None:
            return
        self.run_worker(partial(self._edit, entry, "text"), exclusive=True)

    def action_opening(self) -> None:
        entry = self._shown
        if self._mode != "list" or entry is None:
            return
        if self.shelf != "characters":
            self.status(f"A {self.kind} has no opening.", Kind.WARNING)
            return
        self.run_worker(partial(self._edit, entry, "opening"), exclusive=True)

    async def _edit(self, entry: EntryFull, field: Literal["text", "opening"]) -> None:
        """Hands the text to the reader's editor and saves what comes back over the version
        the editor started from."""
        before = entry.text if field == "text" else (entry.opening or skeletons.OPENING)
        self.status(f"Waiting for {editor_name()} — save and close to come back.")
        after = self.lustjinn.editor(self.lustjinn, before, f"-{self.kind}.txt")
        if after is None or after.strip() == before.strip():
            self.status("Nothing changed.")
            return
        if field == "text":
            saved = await self._save(entry.id, entry.version, text=after.rstrip() + "\n")
        else:
            saved = await self._save(
                entry.id, entry.version, opening=after.strip() or None, clear_opening=True
            )
        if saved is not None:
            await self._load(False, select=saved.id)
            self.status(
                f"Saved. Every story using '{saved.name}' sees the change from its next turn.",
                Kind.SUCCESS,
            )

    async def _save(
        self,
        entry_id: uuid.UUID,
        version: int,
        *,
        name: str | None = None,
        text: str | None = None,
        opening: str | None = None,
        clear_opening: bool = False,
    ) -> EntryFull | None:
        """A save over ``version``; a conflict opens the screen that shows the server's text."""
        api = self.lustjinn.api
        line = self.status_line
        line.busy("Saving")
        try:
            return await api.save_entry(
                self.shelf,
                entry_id,
                version,
                name=name,
                text=text,
                opening=opening,
                clear_opening=clear_opening,
            )
        except ConflictError as conflict:

            async def over(theirs: EntryFull) -> None:
                saved = await api.save_entry(
                    self.shelf,
                    entry_id,
                    theirs.version,
                    name=name,
                    text=text,
                    opening=opening,
                    clear_opening=clear_opening,
                )
                await self._load(False, select=saved.id)
                self.status(f"Saved over version {theirs.version}.", Kind.SUCCESS)

            self.lustjinn.push_screen(ConflictScreen(conflict.detail, conflict.current, over))
        except ApiError as refused:
            self.status(refused.detail, Kind.ERROR)
        except UnreachableError:
            self.lustjinn.lost("The server stopped answering while saving.")
        finally:
            line.idle()
        return None

    # -- the default persona and removing --------------------------------------------------------

    def action_default(self) -> None:
        if self._mode != "list":
            return
        if self.shelf != "personas":
            self.status("Only a persona can be the default.", Kind.WARNING)
            return
        entry = self.selected
        if entry is not None:
            self.run_worker(partial(self._set_default, entry), exclusive=True)

    async def _set_default(self, entry: Entry) -> None:
        clearing = entry.id == self._default_persona
        set_to = await self.lustjinn.call(
            "Setting the default",
            self.lustjinn.api.set_default_persona(None if clearing else entry.id),
        )
        if set_to is None:
            return
        self._default_persona = set_to.default_persona_id
        self.rows.refresh()
        if clearing:
            self.status("No default persona: a story that names none plays as nobody.")
        else:
            self.status(
                f"{entry.name} is the default persona: every story that names none plays as it.",
                Kind.SUCCESS,
            )

    def action_remove(self) -> None:
        entry = self._shown
        if self._mode != "list" or entry is None:
            return
        consequences: Sequence[str]
        if entry.used_by:
            consequences = (
                "The server will refuse while a live story uses it:",
                *(f"  {name}" for name in entry.used_by),
            )
        else:
            consequences = (
                f"No live story uses this {self.kind}. Its history stays; the entry goes.",
                "This cannot be undone.",
            )

        async def remove() -> None:
            await self.lustjinn.api.delete_entry(self.shelf, entry.id)
            await self._load(False)
            self.status(f"Removed '{entry.name}'.", Kind.SUCCESS)

        self.lustjinn.push_screen(
            ConfirmScreen(
                "Remove", f'Delete the {self.kind} "{entry.name}"?', consequences, "Delete", remove
            )
        )
