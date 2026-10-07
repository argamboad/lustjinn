"""The opening screen: the stories. For now the empty frame; the list comes with #48."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.widgets import Static

from lustjinn_tui.legend import Hint
from lustjinn_tui.view import View


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

    DEFAULT_CSS = """
    StoriesScreen .empty { color: $muted; padding: 1 2; }
    """

    def body(self) -> ComposeResult:
        yield Static("No stories yet. Press R to refresh.", classes="empty")
