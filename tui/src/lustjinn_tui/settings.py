"""A story's settings: its model, then its dials (``Views/ChatSettingsView.cs``).

The model is a row like the dials, first because it decides more about a reply than any of
them, stepped through the same ``←→`` and applied by the same ``Enter``. Changes are staged: the
row shows the new value in the warning colour with "(was …)" beside it, and nothing reaches the
server until ``Enter`` applies the lot. ``Esc`` discards staged changes before it leaves. A
refusal (a model the provider does not list, a dial that does not take the value) leaves the
row on what the story really has, with the server's sentence in the status row.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Input, Static

from lustjinn_tui.api import ApiError, Choice, Dial, DialOption, Story, UnreachableError
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.textfmt import fit
from lustjinn_tui.theme import HEADING
from lustjinn_tui.view import View

MODEL_KEY = "__model"


@dataclass(frozen=True, slots=True)
class Row:
    """One setting as the screen steps it: the dial, or the model dressed as a choice dial."""

    dial: Dial

    @property
    def key(self) -> str:
        return self.dial.key


def model_row(default: str, own: str | None, choices: list[Choice]) -> Row:
    """The model as a choice dial: the default first, then the configured choices, and the
    story's own when it is not among them."""
    options = [DialOption(key=default, label=f"Default — {default}", text="the configured model")]
    listed = [c for c in choices if not c.is_default]
    if own is not None and own.lower() != default.lower() and all(c.id != own for c in listed):
        options.append(DialOption(key=own, label=own, text="the story's own model"))
    options.extend(
        DialOption(
            key=c.id,
            label=c.describe(),
            text="checked against the provider's list when applied; prices are list prices",
        )
        for c in listed
    )
    return Row(
        Dial(
            key=MODEL_KEY,
            kind="choice",
            title="Model",
            help="What writes this story's replies and answers. Summaries and facts stay on the "
            "default. A model with a smaller window than the budget shrinks the story's budget.",
            options=options,
        )
    )


def level_index(dial: Dial, value: str | None) -> int | None:
    if value is None:
        return None
    try:
        index = int(value.strip())
    except ValueError:
        return None
    return index if 0 <= index < len(dial.levels) else None


def is_on(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def describe(dial: Dial, value: str | None) -> tuple[str, str]:
    """A value's label and what it means, as the row says them."""
    if value is None:
        return "Not set", "nothing chosen, so the pack's default applies"
    if dial.kind == "scale":
        index = level_index(dial, value)
        if index is not None:
            level = dial.levels[index]
            return level.label, level.text or level.description or ""
    elif dial.kind == "toggle":
        return ("On" if is_on(value) else "Off"), dial.help
    elif dial.kind == "choice":
        found = next((o for o in dial.options if o.key.lower() == value.lower()), None)
        if found is not None:
            return found.label, found.text
    elif dial.kind in {"list", "text"}:
        return value, dial.accepts or ""
    return value, ""


def shorten(help_text: str) -> str:
    stop = help_text.find(". ")
    return help_text[: stop + 1] if stop > 0 else help_text


class Settings(Widget):
    """The rows: a gutter marker on the selected one, the control, the value, the meaning."""

    DEFAULT_CSS = """
    Settings { height: auto; width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Row] = []
        self.applied: dict[str, str] = {}
        self.staged: dict[str, str] = {}
        self.selected = 0

    @property
    def is_dirty(self) -> bool:
        return self.staged != self.applied

    @property
    def current(self) -> Row | None:
        return self.rows[self.selected] if self.rows else None

    def control(self, dial: Dial, value: str | None, selected: bool) -> str:
        if dial.kind == "scale":
            level = level_index(dial, value)
            parts: list[str] = []
            for i in range(len(dial.levels)):
                if i == level:
                    role = "$accent" if selected else "$foreground"
                    parts.append(f"[{role}]●[/]")
                else:
                    parts.append("[$border]○[/]")
            return "[$border]─[/]".join(parts)
        if dial.kind == "toggle":
            on_ = is_on(value)
            return "[$foreground]● On [/]" if on_ else "[$border]○ Off[/]"
        if dial.kind == "choice":
            return "[$border]‹ ›[/]"
        return "[$border]\\[…][/]"

    def render(self) -> Content:
        lines: list[str] = []
        width = max(20, self.size.width - 2)
        for i, row in enumerate(self.rows):
            dial = row.dial
            selected = i == self.selected
            value = self.staged.get(dial.key)
            was = self.applied.get(dial.key)
            changed = value != was
            gutter_role = "$accent" if selected else "$border"
            gutter = f"[{gutter_role}]{'▌ ' if selected else '  '}[/]"
            title_role = "$accent" if selected else "$foreground"
            title = Content(dial.title).markup
            help_text = Content(fit(shorten(dial.help), max(0, width - 4 - len(dial.title)))).markup
            lines.append(f"{gutter}[{title_role}]{title}[/]  [$muted]{help_text}[/]")
            label, meaning = describe(dial, value)
            stated_role = "$warning" if changed else "$success"
            previous = (
                f"  [$muted](was {Content(describe(dial, was)[0]).markup})[/]" if changed else ""
            )
            lines.append(
                f"{gutter}{self.control(dial, value, selected)}  "
                f"[{stated_role}]{Content(label).markup}[/]{previous}"
            )
            if meaning:
                lines.append(f"{gutter}  [$muted]{Content(fit(meaning, width - 4)).markup}[/]")
            lines.append(" ")
        return Content.from_markup("\n".join(lines))


class ChatSettingsScreen(View):
    TITLE = "Settings"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("← →", "Change"),
        Hint("↑ ↓", "Choose setting"),
        Hint("Del", "Clear"),
        Hint("R", "Reload"),
        Hint("Esc", "Back"),
    )
    DIRTY_HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("← →", "Change"),
        Hint("↑ ↓", "Choose setting"),
        Hint("Del", "Clear"),
        Hint("Enter", "Apply"),
        Hint("Esc", "Discard"),
    )
    TYPING_HINTS: ClassVar[tuple[Hint, ...]] = (Hint("Enter", "Keep"), Hint("Esc", "Cancel"))
    AUTO_FOCUS: ClassVar[str | None] = ""
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down,tab", "move(1)", "Down", show=False),
        Binding("pageup", "move(-3)", "Page up", show=False),
        Binding("pagedown", "move(3)", "Page down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("left", "step(-1)", "Lower", show=False),
        Binding("right", "step(1)", "Higher", show=False),
        Binding("delete,backspace", "clear", "Clear", show=False),
        Binding("r,R", "reload", "Reload", show=False),
        Binding("enter", "apply", "Apply", show=False),
    ]

    DEFAULT_CSS = """
    ChatSettingsScreen #body { padding: 0 1; }
    ChatSettingsScreen .heading { margin-top: 1; }
    ChatSettingsScreen VerticalScroll { height: 1fr; }
    ChatSettingsScreen #typed { }
    ChatSettingsScreen #foot { height: 1; }
    """

    def __init__(self, story: Story, on_model: Callable[[str | None], None]) -> None:
        super().__init__()
        self.story = story
        self._on_model = on_model
        self._loaded = False
        self._typing = False
        self._default_model = ""

    def hints(self) -> tuple[Hint, ...]:
        if self._typing:
            return self.TYPING_HINTS
        return self.DIRTY_HINTS if self.settings.is_dirty else self.HINTS

    def body(self) -> ComposeResult:
        yield Static(
            Content.from_markup(
                f"{HEADING}{Content(self.story.name).markup}[/]   "
                "[$muted]these apply to every reply from now on[/]"
            ),
            classes="heading",
        )
        yield Hairline()
        with VerticalScroll():
            yield Static("Reading the story's settings…", classes="muted", id="loading")
            yield Settings()
        yield Input(placeholder="type the value, Enter keeps it", id="typed", compact=True)
        yield Hairline()
        yield Static("", id="foot")

    def on_mount(self) -> None:
        self.query_one(Settings).display = False
        self.query_one("#typed", Input).display = False
        self.run_worker(self._load, exclusive=True)

    @property
    def settings(self) -> Settings:
        return self.query_one(Settings)

    # -- loading --------------------------------------------------------------------------------

    async def _load(self) -> None:
        api = self.lustjinn.api
        read = await self.lustjinn.call("Reading the settings", api.story_dials(self.story.id))
        if read is None:
            return
        pack = await self.lustjinn.call("Reading the settings", api.dial_pack())
        if pack is None:
            return
        own = await self.lustjinn.call("Reading the settings", api.story_model(self.story.id))
        if own is None:
            return
        try:
            choices = await api.models()
        except ApiError, UnreachableError:
            choices = []
        self._default_model = own.default
        settings = self.settings
        by_key = {dial.key: dial for dial in pack}
        settings.rows = [model_row(own.default, own.model, choices)] + [
            Row(by_key[d.key]) for d in read if d.key in by_key and by_key[d.key].enabled
        ]
        applied = {d.key: d.stored for d in read if d.stored is not None}
        applied[MODEL_KEY] = own.model or own.default
        settings.applied = applied
        settings.staged = dict(applied)
        settings.selected = min(settings.selected, max(0, len(settings.rows) - 1))
        self._loaded = True
        self.query_one("#loading").display = False
        settings.display = True
        self._refresh()
        if len(applied) == 1:
            self.status("This story has no settings of its own yet; the pack's defaults apply.")

    def _refresh(self) -> None:
        self.settings.refresh()
        self.refresh_hints()
        foot = self.query_one("#foot", Static)
        if self.settings.is_dirty:
            foot.update(
                Content.from_markup("[$warning]Press Enter to apply these changes to the story.[/]")
            )
        else:
            foot.update(Content.from_markup("[$muted]Nothing changed.[/]"))

    # -- the keys -------------------------------------------------------------------------------

    def action_move(self, delta: int) -> None:
        settings = self.settings
        if not settings.rows:
            return
        settings.selected = max(0, min(settings.selected + delta, len(settings.rows) - 1))
        self._refresh()

    def action_first(self) -> None:
        self.settings.selected = 0
        self._refresh()

    def action_last(self) -> None:
        self.settings.selected = max(0, len(self.settings.rows) - 1)
        self._refresh()

    def action_step(self, delta: int) -> None:
        settings = self.settings
        row = settings.current
        if row is None or not self._loaded:
            return
        dial = row.dial
        value = settings.staged.get(dial.key)
        if dial.kind == "scale":
            # An unset level has no position to move from; the middle is where an untouched
            # dial reads as sitting.
            current = level_index(dial, value)
            if current is None:
                current = len(dial.levels) // 2
            settings.staged[dial.key] = str(max(0, min(current + delta, len(dial.levels) - 1)))
        elif dial.kind == "toggle":
            settings.staged[dial.key] = "false" if is_on(value) else "true"
        elif dial.kind == "choice":
            keys = [o.key for o in dial.options]
            at = next((i for i, k in enumerate(keys) if k.lower() == (value or "").lower()), -1)
            at = (0 if delta > 0 else len(keys) - 1) if at < 0 else (at + delta) % len(keys)
            settings.staged[dial.key] = keys[at]
        else:
            self._type(dial, value)
            return
        self._refresh()

    def _type(self, dial: Dial, value: str | None) -> None:
        """A list or a text is typed, not stepped."""
        self._typing = True
        field = self.query_one("#typed", Input)
        field.value = value or ""
        field.placeholder = f"{dial.title}: {dial.accepts or 'some text'}"
        field.display = True
        field.focus()
        self.refresh_hints()

    @on(Input.Submitted, "#typed")
    def _typed(self, event: Input.Submitted) -> None:
        row = self.settings.current
        self._leave_typing()
        if row is None:
            return
        typed = event.value.strip()
        if typed:
            self.settings.staged[row.key] = typed
        else:
            self.settings.staged.pop(row.key, None)
        self._refresh()

    def _leave_typing(self) -> None:
        self._typing = False
        field = self.query_one("#typed", Input)
        field.display = False
        self.set_focus(None)
        self.refresh_hints()

    def action_clear(self) -> None:
        """Back to "Not set": the pack's default applies again, as if never touched."""
        row = self.settings.current
        if row is None:
            return
        if row.key == MODEL_KEY:
            self.settings.staged[MODEL_KEY] = self._default_model
        else:
            self.settings.staged.pop(row.key, None)
        self._refresh()

    def action_reload(self) -> None:
        if self.settings.is_dirty:
            self.status("Apply or discard the changes first.", Kind.WARNING)
            return
        self.run_worker(self._load, exclusive=True)

    def action_back(self) -> None:
        if self._typing:
            self._leave_typing()
            return
        if self.settings.is_dirty:
            self.settings.staged = dict(self.settings.applied)
            self._refresh()
            self.status("Changes discarded.", Kind.WARNING)
            return
        self.lustjinn.pop_screen()

    def action_apply(self) -> None:
        if not self.settings.is_dirty:
            self.status("Nothing to apply.", Kind.WARNING)
            return
        self.run_worker(partial(self._apply), exclusive=True)

    async def _apply(self) -> None:
        api = self.lustjinn.api
        settings = self.settings
        changed = [
            row
            for row in settings.rows
            if settings.staged.get(row.key) != settings.applied.get(row.key)
        ]
        refused: str | None = None
        applied_titles: list[str] = []
        for row in changed:
            value = settings.staged.get(row.key)
            try:
                if row.key == MODEL_KEY:
                    wanted = None if value == self._default_model else value
                    result = await api.set_model(self.story.id, wanted)
                    settings.staged[MODEL_KEY] = result.model or self._default_model
                    self._on_model(result.model)
                elif value is None:
                    await api.clear_dial(self.story.id, row.key)
                else:
                    stored = await api.set_dial(self.story.id, row.key, value)
                    settings.staged[row.key] = stored.stored or value
            except ApiError as error:
                # Not saved, so the row goes back to what the story really has.
                refused = error.detail
                if row.key in settings.applied:
                    settings.staged[row.key] = settings.applied[row.key]
                else:
                    settings.staged.pop(row.key, None)
                continue
            except UnreachableError:
                self.lustjinn.lost("The server stopped answering while applying the settings.")
                return
            applied_titles.append(
                f"{row.dial.title} → {describe(row.dial, settings.staged.get(row.key))[0]}"
            )
        settings.applied = dict(settings.staged)
        self._refresh()
        if refused is not None:
            self.status(refused, Kind.WARNING)
        elif applied_titles:
            self.status("Applied: " + ", ".join(applied_titles) + ".", Kind.SUCCESS)
