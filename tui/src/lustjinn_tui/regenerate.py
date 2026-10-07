"""Asking for the last reply again, saying what was wrong with it (``Views/RegenerateView.cs``).

The reasons are the API's own list (``lustjinn.regenerate.Reason``), because the API records the
one picked and accepts only values it knows; the instructions are optional and go alongside.
Nothing is asked for until Enter: this spends money and the reply it replaces is not kept, so
the reply about to be discarded is shown first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Static, TextArea

from lustjinn_tui import prose
from lustjinn_tui.api import Message
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.textfmt import fit, pad
from lustjinn_tui.theme import HEADING
from lustjinn_tui.view import View


@dataclass(frozen=True, slots=True)
class Reason:
    value: str
    label: str
    describe: str


REASONS: Final[tuple[Reason, ...]] = (
    Reason("none", "No reason", "ask for another reply without saying why"),
    Reason("steer", "Guide the reply", "just write it differently — say how in the instructions"),
    Reason("bad-memory", "Bad memory", "it contradicted something established earlier"),
    Reason("looping", "Looping", "it repeated itself, or the scene stopped moving"),
    Reason("acting-for-user", "Writing my actions", "it wrote your actions or words for you"),
    Reason("too-short", "Too short", "there was not enough of it"),
    Reason("too-long", "Too long", "there was too much of it"),
    Reason("wrong-format", "Wrong format", "the prose, dialogue or emphasis came out wrong"),
    Reason("refusing", "AI refusing", "it declined to answer"),
)
INSTRUCTION_LIMIT: Final = 2000  # the API's ceiling on the instructions

OnRegenerate = Callable[[str, str | None], None]


class Reasons(Widget):
    """The reasons as radio rows: the picked one in accent with its marker, every description
    muted beside its label."""

    DEFAULT_CSS = """
    Reasons { height: auto; width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.index = 1  # "Guide the reply", as the donor opened

    @property
    def reason(self) -> Reason:
        return REASONS[self.index]

    def move(self, delta: int) -> None:
        self.index = (self.index + delta) % len(REASONS)
        self.refresh()

    def render(self) -> Content:
        lines: list[Content] = []
        for i, reason in enumerate(REASONS):
            picked = i == self.index
            role = "$accent" if picked else "$border"
            marker = "▌ " if picked else "  "
            dot = "● " if picked else "○ "
            label_role = "$accent" if picked else "$foreground"
            label = Content(pad(reason.label, 20)).markup
            lines.append(
                Content.from_markup(
                    f"[{role}]{marker}{dot}[/][{label_role}]{label}[/]"
                    f"[$muted]{Content(reason.describe).markup}[/]"
                )
            )
        return Content("\n").join(lines)


class RegenerateScreen(View):
    TITLE = "Regenerate"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("↑ ↓", "Choose a reason"),
        Hint("I", "Add instructions"),
        Hint("Enter", "Regenerate"),
        Hint("Esc", "Cancel"),
    )
    WRITING_HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Esc", "Done writing"),
        Hint("Enter", "New line"),
    )
    AUTO_FOCUS: ClassVar[str | None] = ""
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move(-1)", "Previous reason", show=False),
        Binding("down,tab", "move(1)", "Next reason", show=False),
        Binding("i,I", "write", "Add instructions", show=False),
        Binding("enter", "submit", "Regenerate", show=False),
    ]

    DEFAULT_CSS = """
    RegenerateScreen #body { padding: 1 2; }
    RegenerateScreen .replacing { color: $muted; padding-left: 2; }
    RegenerateScreen .heading { margin-top: 1; }
    RegenerateScreen .caption { margin-top: 1; }
    RegenerateScreen TextArea {
        height: auto; min-height: 1; max-height: 5; border: none; padding: 0 0 0 2;
        background: $background;
    }
    RegenerateScreen TextArea:focus { border: none; }
    """

    def __init__(self, replacing: Message, on_regenerate: OnRegenerate) -> None:
        super().__init__()
        self._replacing = replacing
        self._on_regenerate = on_regenerate
        self._writing = False

    def hints(self) -> Sequence[Hint]:
        return self.WRITING_HINTS if self._writing else self.HINTS

    def body(self) -> ComposeResult:
        yield Static(
            Content.from_markup(
                f"{HEADING}Replace this reply with a new one[/]"
                "   [$muted]this costs money and the current wording is not kept[/]"
            )
        )
        yield Hairline()
        # Two lines of what is about to go: enough to recognise it without burying the choice.
        flat = prose.plain(self._replacing.text.replace("\n", " "))
        yield Static(fit(flat, 2 * max(20, self.lustjinn.size.width - 8)), classes="replacing")
        yield Static(
            Content.from_markup(
                f"{HEADING}What was wrong with it?[/]   "
                "[$muted]the reason is sent with the request[/]"
            ),
            classes="heading",
        )
        yield Hairline()
        yield Reasons()
        yield Hairline()
        yield Static("", classes="caption", id="caption")
        yield TextArea(id="instructions", compact=True, soft_wrap=True)

    def on_mount(self) -> None:
        self._show_caption()

    @property
    def reasons(self) -> Reasons:
        return self.query_one(Reasons)

    @property
    def instructions(self) -> str:
        return self.query_one("#instructions", TextArea).text.strip()

    def _show_caption(self) -> None:
        length = len(self.query_one("#instructions", TextArea).text)
        over = length > INSTRUCTION_LIMIT
        count_role = "$error" if over else "$muted"
        note = "Esc when done" if self._writing else "optional — press I to write some"
        self.query_one("#caption", Static).update(
            Content.from_markup(
                f"[$accent]Instructions[/] [{count_role}]{length:,}/{INSTRUCTION_LIMIT:,}[/]"
                f"  [$muted]{note}[/]"
            )
        )

    @on(TextArea.Changed)
    def _typed(self) -> None:
        self._show_caption()

    def action_move(self, delta: int) -> None:
        self.reasons.move(delta)

    def action_write(self) -> None:
        self._writing = True
        self.query_one("#instructions", TextArea).focus()
        self.refresh_hints()
        self._show_caption()
        self.status("Type your instructions. Esc when done.")

    def action_back(self) -> None:
        if self._writing:
            self._writing = False
            self.set_focus(None)
            self.refresh_hints()
            self._show_caption()
            return
        self.lustjinn.pop_screen()

    def action_submit(self) -> None:
        instructions = self.instructions
        if len(instructions) > INSTRUCTION_LIMIT:
            self.status(
                f"The instructions are {len(instructions):,} characters and the limit is "
                f"{INSTRUCTION_LIMIT:,}. Nothing has been asked for.",
                Kind.WARNING,
            )
            return
        reason = self.reasons.reason.value
        self.lustjinn.pop_screen()
        self._on_regenerate(reason, instructions or None)
