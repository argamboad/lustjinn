"""Exporting a story (``Views/ExportView.cs``): the transcript as Markdown, JSON or plain text,
previewed, then written to a file or copied.

The API renders the document (``GET /stories/{id}/export``, #66) and names the file; the client
only chooses the format and where the file goes — ``export_directory`` in the config, under
the config directory when relative.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import ClassVar, cast

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.content import Content
from textual.widgets import Static

from lustjinn_tui.api import Export, ExportFormat, Story
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.theme import HEADING, SELECTION
from lustjinn_tui.view import View

FORMATS: tuple[ExportFormat, ...] = ("markdown", "json", "text")
DESCRIBED: dict[str, str] = {"markdown": "Markdown", "json": "JSON", "text": "Plain text"}


def write_export(directory: Path, export: Export) -> Path:
    """Writes the document under its server-given name, never over an existing file."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / export.filename
    n = 2
    while path.exists():
        path = directory / f"{Path(export.filename).stem} ({n}){Path(export.filename).suffix}"
        n += 1
    path.write_text(export.text, encoding="utf-8")
    return path


class ExportScreen(View):
    TITLE = "Export"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("← →", "Change format"),
        Hint("Enter", "Write to a file"),
        Hint("C", "Copy to clipboard"),
        Hint("↑ ↓", "Scroll preview"),
        Hint("Esc", "Back"),
    )
    AUTO_FOCUS: ClassVar[str | None] = ""
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "format(-1)", "Previous format", show=False),
        Binding("right,tab", "format(1)", "Next format", show=False),
        Binding("up", "scroll(-1)", "Up", show=False),
        Binding("down", "scroll(1)", "Down", show=False),
        Binding("pageup", "scroll_page(-1)", "Page up", show=False),
        Binding("pagedown", "scroll_page(1)", "Page down", show=False),
        Binding("enter", "write", "Write", show=False),
        Binding("c,C", "copy", "Copy", show=False),
    ]

    DEFAULT_CSS = """
    ExportScreen #body { padding: 0 1; }
    ExportScreen #head { height: 1; margin-top: 1; }
    ExportScreen VerticalScroll { height: 1fr; }
    ExportScreen .preview { padding-left: 1; }
    """

    def __init__(self, story: Story) -> None:
        super().__init__()
        self.story = story
        self.format_index = 0
        self.export: Export | None = None

    @property
    def fmt(self) -> ExportFormat:
        return FORMATS[self.format_index]

    def body(self) -> ComposeResult:
        yield Static("", id="head")
        yield Hairline()
        with VerticalScroll():
            yield Static("", classes="preview", id="preview")

    def on_mount(self) -> None:
        self._show_head()
        self.run_worker(self._preview, exclusive=True)

    def _show_head(self) -> None:
        tabs: list[str] = []
        for i, fmt in enumerate(FORMATS):
            label = Content(f" {DESCRIBED[fmt]} ").markup
            tabs.append(
                f"{SELECTION}{label}[/]" if i == self.format_index else f"[$muted]{label}[/]"
            )
        name = Content(self.export.filename if self.export else self.story.name).markup
        self.query_one("#head", Static).update(
            Content.from_markup(f"{HEADING}{name}[/]   " + "  ".join(tabs))
        )

    async def _preview(self) -> None:
        rendered = await self.lustjinn.call(
            f"Rendering as {DESCRIBED[self.fmt]}", self.lustjinn.api.export(self.story.id, self.fmt)
        )
        if rendered is None:
            return
        self.export = rendered
        self.query_one("#preview", Static).update(rendered.text)
        self.query_one(VerticalScroll).scroll_home(animate=False)
        self._show_head()

    # -- the keys -------------------------------------------------------------------------------

    def action_format(self, delta: int) -> None:
        self.format_index = (self.format_index + delta) % len(FORMATS)
        self.export = None
        self._show_head()
        self.run_worker(self._preview, exclusive=True)

    def action_scroll(self, direction: int) -> None:
        self.query_one(VerticalScroll).scroll_relative(y=direction, animate=False)

    def action_scroll_page(self, direction: int) -> None:
        scroller = self.query_one(VerticalScroll)
        if direction > 0:
            scroller.scroll_page_down(animate=False)
        else:
            scroller.scroll_page_up(animate=False)

    def action_write(self) -> None:
        export = self.export
        if export is None:
            self.status("The preview has not arrived yet.", Kind.WARNING)
            return
        self.run_worker(partial(self._write, export), exclusive=True)

    async def _write(self, export: Export) -> None:
        directory = self.lustjinn.config.export_path()
        try:
            path = write_export(directory, export)
        except OSError as error:
            self.status(f"Could not write to {directory}: {error}", Kind.ERROR)
            return
        app = self.lustjinn
        below = cast("View | None", app.screen_stack[-2] if len(app.screen_stack) > 1 else None)
        app.pop_screen()
        if isinstance(below, View):
            below.status(f"Written to {path}", Kind.SUCCESS)

    def action_copy(self) -> None:
        export = self.export
        if export is None:
            self.status("The preview has not arrived yet.", Kind.WARNING)
            return
        app = self.lustjinn
        app.copy_to_clipboard(export.text)
        below = app.screen_stack[-2] if len(app.screen_stack) > 1 else None
        app.pop_screen()
        if isinstance(below, View):
            below.status("Copied to the clipboard.", Kind.SUCCESS)
