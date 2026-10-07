"""Two screens the composer's commands open.

``TextPaneScreen`` (``Views/TextPaneView.cs``) is a page of text, scrolled and then dismissed:
the card, the persona, the facts, the meters, the audit, the cost and the command list are
seven unrelated things that are all, on screen, a body of text too long for the status row and
not worth a screen of its own. It holds a copy of its lines rather than a callback that produces
them: these are answers to "what is true right now", and right now was when the command was
typed.

``AskScreen`` (``Views/AskView.cs``) is the answer to a question asked out of character, and the
one decision it needs. The answer is not in the story and never will be, which is what makes
it safe to ask anything — and dangerous in one way: a model asked something the story never
settled answers confidently rather than saying so, and three turns later the story contradicts a
detail nothing recorded. So the pane offers exactly one thing: ``F`` pins the answer as a fact
the next prompt carries and the extractor cannot retire; anything else closes the pane and the
answer is gone.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.content import Content
from textual.widgets import Static

from lustjinn_tui.api import Aside
from lustjinn_tui.commands import Report
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.theme import HEADING
from lustjinn_tui.view import View

SCROLL_HINTS: tuple[Hint, ...] = (Hint("↑↓ PgUp PgDn", "Scroll"), Hint("Esc", "Close"))
SCROLL_BINDINGS: list[BindingType] = [
    Binding("up", "scroll(-1)", "Up", show=False),
    Binding("down", "scroll(1)", "Down", show=False),
    Binding("pageup", "scroll_page(-1)", "Page up", show=False),
    Binding("pagedown", "scroll_page(1)", "Page down", show=False),
    Binding("home", "scroll_home", "Top", show=False),
    Binding("end", "scroll_end", "Bottom", show=False),
]


class Scrolled(View):
    """A view whose body scrolls under the keys, without taking the focus from the screen."""

    BINDINGS: ClassVar[list[BindingType]] = SCROLL_BINDINGS
    AUTO_FOCUS: ClassVar[str | None] = ""

    @property
    def scroller(self) -> VerticalScroll:
        return self.query_one(VerticalScroll)

    def action_scroll(self, direction: int) -> None:
        self.scroller.scroll_relative(y=direction, animate=False)

    def action_scroll_page(self, direction: int) -> None:
        if direction > 0:
            self.scroller.scroll_page_down(animate=False)
        else:
            self.scroller.scroll_page_up(animate=False)

    def action_scroll_home(self) -> None:
        self.scroller.scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        self.scroller.scroll_end(animate=False)


class TextPaneScreen(Scrolled):
    HINTS: ClassVar[tuple[Hint, ...]] = SCROLL_HINTS

    DEFAULT_CSS = """
    TextPaneScreen #body { padding: 0 2; }
    TextPaneScreen .heading { margin-top: 1; }
    TextPaneScreen VerticalScroll { height: 1fr; }
    TextPaneScreen .line { padding-left: 2; }
    """

    def __init__(self, report: Report) -> None:
        super().__init__()
        self.report = report
        self.title = report.title

    def body(self) -> ComposeResult:
        title = Content(self.report.title).markup
        subtitle = Content(self.report.subtitle).markup
        yield Static(
            Content.from_markup(f"{HEADING}{title}[/]   [$muted]{subtitle}[/]"), classes="heading"
        )
        yield Hairline()
        with VerticalScroll():
            yield Static("\n".join(self.report.lines), classes="line")

    @property
    def lines(self) -> Sequence[str]:
        return self.report.lines


class AskScreen(Scrolled):
    TITLE = "Asked"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("F", "Pin as a fact"),
        Hint("↑↓ PgUp PgDn", "Scroll"),
        Hint("Esc", "Discard"),
    )
    PINNED_HINTS: ClassVar[tuple[Hint, ...]] = SCROLL_HINTS
    BINDINGS: ClassVar[list[BindingType]] = [
        *SCROLL_BINDINGS,
        Binding("f,F", "pin", "Pin as a fact", show=False),
    ]

    DEFAULT_CSS = """
    AskScreen #body { padding: 0 2; }
    AskScreen .heading { margin-top: 1; }
    AskScreen VerticalScroll { height: 1fr; }
    AskScreen .question { color: $accent; padding-left: 2; margin-bottom: 1; }
    AskScreen .answer { padding-left: 2; }
    AskScreen #foot { height: 1; }
    """

    def __init__(self, story_id: uuid.UUID, subject: str, aside: Aside) -> None:
        super().__init__()
        self.story_id = story_id
        self.subject = subject
        self.aside = aside
        self.pinned = False

    def hints(self) -> Sequence[Hint]:
        return self.PINNED_HINTS if self.pinned else self.HINTS

    def body(self) -> ComposeResult:
        yield Static(
            Content.from_markup(
                f"{HEADING}Out of character[/]   "
                "[$muted]not in the transcript, not in any later prompt[/]"
            ),
            classes="heading",
        )
        yield Hairline()
        with VerticalScroll():
            yield Static(self.aside.question, classes="question")
            yield Static(self.aside.answer, classes="answer")
        yield Hairline()
        yield Static(self._foot(), id="foot")

    def _foot(self) -> Content:
        if self.pinned:
            return Content.from_markup(
                "  [$success]Pinned. It is in the world layer from the next turn on.[/]"
            )
        model = Content(self.aside.model or "the model").markup
        return Content.from_markup(
            f"  [$muted]answered by {model}   F pins this as a fact · Esc discards it[/]"
        )

    async def action_pin(self) -> None:
        if self.pinned:
            self.status("Already pinned.")
            return
        text = self.aside.answer.strip()
        if not text:
            self.status("There is nothing to pin.", Kind.WARNING)
            return
        pinned = await self.lustjinn.call(
            "Pinning", self.lustjinn.api.add_fact(self.story_id, self.subject, text)
        )
        if pinned is None:
            return
        self.pinned = True
        self.query_one("#foot", Static).update(self._foot())
        self.refresh_hints()
        self.status(
            f"Pinned under {self.subject}. The extractor cannot retire it; /facts shows it.",
            Kind.SUCCESS,
        )
