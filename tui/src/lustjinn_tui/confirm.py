"""A question before something that cannot be undone (``Views/ConfirmView.cs``): the question in
red, what follows from a yes, and ``Enter`` as the only key that says yes. Every other key says
no and leaves everything as it is.

The screen leaves the stack before the work runs, so what the work says — a status, a refusal —
lands on the screen that asked, where the reader is by then.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static

from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.view import View


class ConfirmScreen(View):
    DEFAULT_CSS = """
    ConfirmScreen #body { padding: 1 2; }
    ConfirmScreen .question { color: $error; }
    ConfirmScreen .consequence { padding-left: 2; }
    ConfirmScreen .keys { margin-top: 1; }
    """

    BINDINGS: ClassVar = []  # the keys are read directly: anything but Enter cancels

    def __init__(
        self,
        title: str,
        question: str,
        consequences: Sequence[str],
        confirm_label: str,
        confirm: Callable[[], Awaitable[object]],
    ) -> None:
        super().__init__()
        self.title = title
        self._question = question
        self._consequences = tuple(consequences)
        self._label = confirm_label
        self._confirm = confirm
        self._answered = False

    def hints(self) -> Sequence[Hint]:
        return (Hint("Enter", self._label), Hint("Esc", "Cancel"))

    def body(self) -> ComposeResult:
        yield Static(self._question, classes="question")
        yield Hairline()
        for line in self._consequences:
            yield Static(line, classes="consequence")
        yield Static(
            Content.from_markup(
                f"[$error]Enter[/] [$muted]to {Content(self._label.lower()).markup}[/]   "
                "[$accent]Esc[/] [$muted]to leave everything as it is[/]"
            ),
            classes="keys",
        )

    def on_key(self, event: events.Key) -> None:
        if self._answered:
            return
        event.stop()
        event.prevent_default()
        self._answered = True
        app = self.lustjinn
        below = app.screen_stack[-2]
        app.pop_screen()
        if event.key == "enter":
            app.run_worker(partial(app.call, self._label, self._confirm()), exclusive=False)
        elif isinstance(below, View):
            below.status("Cancelled.", Kind.INFO)
