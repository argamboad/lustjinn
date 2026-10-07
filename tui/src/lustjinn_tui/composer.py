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

from lustjinn_tui.completion import Offer, Provider

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

    class Offered(Message):
        """The completions changed: the strip under the composer should show ``offer``."""

        def __init__(self, composer: Composer, offer: Offer | None) -> None:
            super().__init__()
            self.composer = composer
            self.offer = offer

        @property
        def control(self) -> Composer:
            return self.composer

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, soft_wrap=True, show_line_numbers=False, compact=True)
        self.newline_on_enter = False
        self.providers: list[Provider] = []
        self.offer: Offer | None = None
        self.choice = 0

    # -- completion ---------------------------------------------------------------------------

    def refresh_offers(self) -> None:
        """Recomputed after every key rather than only the ones that obviously matter: what
        opens and closes the strip is where the caret ended up, and that changes on movement
        and undo as much as on typing. The first provider with an offer wins."""
        row, column = self.cursor_location
        line = self.document.get_line(row)
        offer = None
        for provider in self.providers:
            offer = provider(line, column, row == 0)
            if offer is not None:
                break
        if offer != self.offer:
            self.offer = offer
            self.choice = 0
            self.post_message(self.Offered(self, offer))

    def dismiss_offers(self) -> None:
        if self.offer is not None:
            self.offer = None
            self.post_message(self.Offered(self, None))

    def accept(self) -> None:
        """Replaces the typed token with the chosen completion."""
        if self.offer is None:
            return
        chosen = self.offer.completions[self.choice % len(self.offer.completions)]
        row = self.cursor_location[0]
        self.replace(
            chosen.insert, (row, self.offer.start), (row, self.offer.start + self.offer.length)
        )
        self.move_cursor((row, self.offer.start + len(chosen.insert)))
        self.dismiss_offers()

    async def _on_key(self, event: events.Key) -> None:
        if self.offer is not None:
            claimed = True
            if event.key == "tab":
                self.accept()
            elif event.key == "up":
                self.choice = (self.choice - 1) % len(self.offer.completions)
                self.post_message(self.Offered(self, self.offer))
            elif event.key == "down":
                self.choice = (self.choice + 1) % len(self.offer.completions)
                self.post_message(self.Offered(self, self.offer))
            elif event.key == "escape":
                self.dismiss_offers()  # the list first; the composer only on a second press
            else:
                claimed = False
            if claimed:
                event.stop()
                event.prevent_default()
                return
        # Enter sends and Alt+Enter breaks the line; on a phone the two change places.
        sends = event.key in NEWLINE_KEYS if self.newline_on_enter else event.key == "enter"
        breaks = event.key == "enter" if self.newline_on_enter else event.key in NEWLINE_KEYS
        if sends:
            event.stop()
            event.prevent_default()
            self.post_message(self.Send(self))
            return
        if breaks:
            event.stop()
            event.prevent_default()
            self.insert("\n")
        elif event.key == "tab":
            event.stop()
            event.prevent_default()
            self.insert("  ")
        else:
            await super()._on_key(event)
        self.refresh_offers()


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
