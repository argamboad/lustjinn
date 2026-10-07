"""The composer: where a message is written (``Ui/TextInput.cs`` and the composer half of
``Views/ConversationView.cs``), on Textual's ``TextArea``.

``Enter`` sends and ``Alt+Enter`` breaks the line, which is the convention every chat client
uses — the common case should be one keystroke. A line break inside *pasted* text is part of the
message, never a send: getting that wrong sends half of whatever was pasted, which costs money
and cannot be taken back. Textual delivers a paste as one ``Paste`` event (bracketed paste, when
the terminal supports it), so the text area inserts it whole and ``Enter`` never sees it.

On a phone the two keys change places (#53): a touch keyboard's Enter is a new line in every
text box on the device, and a send is permanent and billed.

.NET readers: a ``TextBox`` subclass that raises ``Send`` on Enter instead of inserting it.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual import events
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea

NEWLINE_KEYS: Final = frozenset({"alt+enter", "shift+enter", "ctrl+enter", "ctrl+j"})


def word_count(text: str) -> int:
    return len(text.split())


class Composer(TextArea):
    """Posts ``Send`` on Enter; ``newline_on_enter`` swaps the keys for a phone."""

    DEFAULT_CSS = """
    Composer {
        height: auto;
        min-height: 1;
        max-height: 50vh;
        border: none;
        padding: 0 0 0 2;
        background: $background;
    }
    Composer:focus { border: none; }
    """

    class Send(Message):
        def __init__(self, composer: Composer) -> None:
            super().__init__()
            self.composer = composer

        @property
        def control(self) -> Composer:
            return self.composer

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, soft_wrap=True, show_line_numbers=False, compact=True)
        self.newline_on_enter = False

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter" and not self.newline_on_enter:
            event.stop()
            event.prevent_default()
            self.post_message(self.Send(self))
            return
        if event.key in NEWLINE_KEYS or (event.key == "enter" and self.newline_on_enter):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self.insert("  ")
            return
        await super()._on_key(event)


class Caption(Widget):
    """The row over the composer: who is writing, how much, and which key sends."""

    DEFAULT_CSS = """
    Caption { height: 1; width: 1fr; }
    """

    HINT: ClassVar[str] = "Enter sends · Alt+Enter for a new line"
    PHONE_HINT: ClassVar[str] = "Enter is a new line"

    def __init__(self) -> None:
        super().__init__()
        self._length = 0
        self._words = 0
        self._phone = False

    def measure(self, text: str, *, phone: bool = False) -> None:
        self._length, self._words, self._phone = len(text), word_count(text), phone
        self.refresh()

    def render(self) -> Content:
        hint = self.PHONE_HINT if self._phone else self.HINT
        return Content.from_markup(
            f"[$accent]You[/]  [$muted]{self._length:,} characters · {self._words:,} words · "
            f"{hint}[/]"
        )
