"""The conversation: where a story is read and written. For now the frame with the story's
name; the transcript, the composer and the streamed turns come with #49."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.widgets import Static

from lustjinn_tui.api import Story
from lustjinn_tui.legend import Hint
from lustjinn_tui.view import View


class ConversationScreen(View):
    HINTS: ClassVar[tuple[Hint, ...]] = (Hint("Esc", "Back"), Hint("Q", "Quit"))

    DEFAULT_CSS = """
    ConversationScreen #body { padding: 1 2; }
    ConversationScreen .with { color: $accent; }
    """

    def __init__(self, story: Story) -> None:
        super().__init__()
        self.story = story
        self.title = story.name

    def body(self) -> ComposeResult:
        yield Static(f"with {self.story.character_name}", classes="with")
