"""Starting a story from inside the terminal (``Views/NewChatView.cs``): a name, a character and
a persona picked from the library, a model picked from the configured choices.

The pickers offer names, never contents, because that is what a story stores: the ids go to
the database, the cards stay in the library, and editing a card later reaches this story too.
Under the fields, the picked character's card and the persona facing it stand side by side,
whole, because whether this is the right person to walk into that place is a question about
both at once — and the text is going into every prompt anyway, so showing it costs nothing.

The donor also wrote the opening here; the API takes it from the character instead (#55), so
the form stops at the model.

.NET readers: a form with a focus chain. Textual walks it with Tab on its own; the pickers are
focusable widgets that handle ``←``/``→`` themselves and post a message when they change, the
way a custom control raises an event.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from lustjinn_tui.api import ApiError, Choice, Defaults, Entry, Story, UnreachableError
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.conversation import ConversationScreen
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.status import Kind
from lustjinn_tui.view import View

LABEL_WIDTH = 11


class Picker(Widget, can_focus=True):
    """One field that cycles through choices with ``←`` and ``→``: a label, the chosen value,
    and the arrows as a reminder while it has the focus. The first choice is the "none" or
    "default" slot and reads muted."""

    DEFAULT_CSS = """
    Picker { height: 1; width: 1fr; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
        Binding("enter", "submit", "Next field", show=False),
    ]

    class Changed(Message):
        def __init__(self, picker: Picker, index: int) -> None:
            super().__init__()
            self.picker = picker
            self.index = index

        @property
        def control(self) -> Picker:
            return self.picker  # what ``@on(Picker.Changed, "#pick-character")`` matches against

    class Submitted(Message):
        def __init__(self, picker: Picker) -> None:
            super().__init__()
            self.picker = picker

        @property
        def control(self) -> Picker:
            return self.picker

    def __init__(self, label: str, choices: list[str], *, id: str) -> None:
        super().__init__(id=id)
        self.label = label
        self._choices = choices
        self.index = 0

    @property
    def choices(self) -> list[str]:
        return self._choices

    def set_choices(self, choices: list[str]) -> None:
        self._choices = choices
        self.index = min(self.index, max(0, len(choices) - 1))
        self.refresh()

    @property
    def value(self) -> str:
        return self._choices[self.index] if self._choices else ""

    def action_step(self, delta: int) -> None:
        if len(self._choices) < 2:
            return
        self.index = (self.index + delta) % len(self._choices)
        self.refresh()
        self.post_message(self.Changed(self, self.index))

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self))

    def render(self) -> Content:
        focused = self.has_focus
        label = Content(self.label.ljust(LABEL_WIDTH)).markup
        label_role = "$accent" if focused else "$muted"
        value_role = "$muted" if self.index == 0 else "$foreground"
        arrows = "  [$muted]←→[/]" if focused else ""
        return Content.from_markup(
            f"[{label_role}]{label}[/][{value_role}]{Content(self.value).markup}[/]{arrows}"
        )

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


class Panel(Vertical):
    """A caption over a rule over scrolling text: one half of the preview under the form."""

    DEFAULT_CSS = """
    Panel { width: 1fr; height: 1fr; padding: 0 1; }
    Panel .caption { color: $primary; text-style: bold; height: 1; }
    Panel VerticalScroll { height: 1fr; }
    """

    def __init__(self, caption: str, *, id: str) -> None:
        super().__init__(id=id)
        self._caption = caption
        self.text = ""

    def compose(self) -> ComposeResult:
        yield Static(self._caption, classes="caption")
        yield Hairline()
        with VerticalScroll():
            yield Static("", classes="text")

    def show(self, text: str | None) -> None:
        self.text = text or ""
        self.query_one(".text", Static).update(self.text)
        self.query_one(VerticalScroll).scroll_home(animate=False)
        self.display = bool(text)

    def page(self, direction: int) -> None:
        scroll = self.query_one(VerticalScroll)
        if direction > 0:
            scroll.scroll_page_down(animate=False)
        else:
            scroll.scroll_page_up(animate=False)


def default_name(character: str, today: datetime | None = None) -> str:
    """``Elena, 7 October``: what a story is called when the reader names nothing, so nobody
    types the character's name three times to start."""
    when = today or datetime.now()  # the reader's own clock: this is a label, not a timestamp
    return f"{character}, {when.day} {when.strftime('%B')}"


class NewStoryScreen(View):
    TITLE = "New story"
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Tab", "Next field"),
        Hint("←→", "Pick"),
        Hint("PgUp/PgDn", "Read the panel"),
        Hint("Ctrl+S", "Create"),
        Hint("Esc", "Cancel"),
    )
    AUTO_FOCUS: ClassVar[str | None] = "#name"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s,ctrl+enter", "create", "Create", show=False, priority=True),
        Binding("down", "app.focus_next", "Next field", show=False),
        Binding("up", "app.focus_previous", "Previous field", show=False),
        Binding("pageup", "page(-1)", "Read up", show=False),
        Binding("pagedown", "page(1)", "Read down", show=False),
    ]

    DEFAULT_CSS = """
    NewStoryScreen #form { height: auto; padding: 1 2 0 2; }
    NewStoryScreen #name-row { height: 1; }
    NewStoryScreen #name-row .label { width: 11; color: $muted; }
    NewStoryScreen #name-row Input { width: 1fr; }
    NewStoryScreen #name-row Input:focus { color: $foreground; }
    NewStoryScreen #form Hairline { margin-top: 1; }
    NewStoryScreen #panels { height: 1fr; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._characters: list[Entry] = []
        self._personas: list[Entry] = []
        self._defaults = Defaults()
        self._models: list[Choice] = []
        self._touched_pick = False

    def body(self) -> ComposeResult:
        with Vertical(id="form"):
            with Horizontal(id="name-row"):
                yield Static("Name".ljust(LABEL_WIDTH), classes="label")
                yield Input(placeholder="how it appears in your list", id="name", compact=True)
            yield Picker("Character", ["(reading the library…)"], id="pick-character")
            yield Picker("Persona", ["(default)"], id="pick-persona")
            yield Picker("Model", ["(default)"], id="pick-model")
            yield Hairline()
        with Horizontal(id="panels"):
            yield Panel("Character preview", id="world")
            yield Panel("Persona", id="persona-text")

    def on_mount(self) -> None:
        self.query_one("#world", Panel).display = False
        self.query_one("#persona-text", Panel).display = False
        self.run_worker(self._read_library, exclusive=True)

    # -- the pickers ----------------------------------------------------------------------------

    def picker(self, id: str) -> Picker:
        return self.query_one(f"#pick-{id}", Picker)

    @property
    def character(self) -> Entry | None:
        index = self.picker("character").index
        return self._characters[index] if self._characters else None

    @property
    def persona(self) -> Entry | None:
        """The picked persona; None is the default slot."""
        index = self.picker("persona").index
        return self._personas[index - 1] if index > 0 else None

    @property
    def model(self) -> Choice | None:
        """The picked model; None is the default slot."""
        index = self.picker("model").index
        return self._models[index - 1] if index > 0 else None

    @property
    def touched(self) -> bool:
        return bool(self.query_one("#name", Input).value) or self._touched_pick

    async def _read_library(self) -> None:
        api = self.lustjinn.api
        read = await self.lustjinn.call(
            "Reading the library",
            asyncio.gather(api.entries("characters"), api.entries("personas"), api.defaults()),
        )
        if read is None:
            return
        self._characters, self._personas, self._defaults = read
        if self._characters:
            self.picker("character").set_choices([c.name for c in self._characters])
        else:
            self.picker("character").set_choices(["(the library has no characters yet)"])
            self.status("The library has no characters yet. Add one first.", Kind.WARNING)
        default = self._defaults.default_persona_name
        self.picker("persona").set_choices(
            [f"(default: {default})" if default else "(none)", *(p.name for p in self._personas)]
        )
        await self._describe_character()
        await self._describe_persona()
        # The prices beside the models come from the provider's list: read on arrival and never
        # waited for. The form works without them and says only "(default)".
        self.run_worker(self._read_models, exclusive=False)

    async def _read_models(self) -> None:
        try:
            choices = await self.lustjinn.api.models()
        except ApiError, UnreachableError:
            return
        self._models = [c for c in choices if not c.is_default]
        default = next((c.id for c in choices if c.is_default), None)
        self.picker("model").set_choices(
            [f"(default: {default})" if default else "(default)"]
            + [c.describe() for c in self._models]
        )

    @on(Picker.Changed, "#pick-character")
    async def _character_picked(self) -> None:
        await self._describe_character()

    @on(Picker.Changed, "#pick-persona")
    async def _persona_picked(self) -> None:
        self._touched_pick = True
        await self._describe_persona()

    @on(Picker.Changed, "#pick-model")
    def _model_picked(self) -> None:
        self._touched_pick = True

    async def _describe_character(self) -> None:
        character = self.character
        text = None
        if character is not None:
            full = await self.lustjinn.call(
                "Reading the card", self.lustjinn.api.entry("characters", character.id)
            )
            text = full.text if full is not None else None
        self.query_one("#world", Panel).show(text)

    async def _describe_persona(self) -> None:
        """The persona that will be sent: the picked one, or the default, which is a real
        persona that will really go into the prompt."""
        persona_id: uuid.UUID | None
        persona = self.persona
        persona_id = persona.id if persona is not None else self._defaults.default_persona_id
        text = None
        if persona_id is not None:
            full = await self.lustjinn.call(
                "Reading the persona", self.lustjinn.api.entry("personas", persona_id)
            )
            text = full.text if full is not None else None
        self.query_one("#persona-text", Panel).show(text)

    # -- the keys -------------------------------------------------------------------------------

    @on(Input.Submitted, "#name")
    def _name_entered(self) -> None:
        self.picker("character").focus()

    @on(Picker.Submitted)
    def _picker_entered(self, event: Picker.Submitted) -> None:
        """Enter walks the fields, because that is what typing a form feels like; on the last
        one it creates."""
        if event.picker.id == "pick-model":
            self.action_create()
        else:
            self.lustjinn.action_focus_next()

    def action_page(self, direction: int) -> None:
        """The page keys read whichever half the focus is on: the persona while the persona is
        being picked, the character's world otherwise."""
        on_persona = self.focused is not None and self.focused.id == "pick-persona"
        self.query_one("#persona-text" if on_persona else "#world", Panel).page(direction)

    def action_back(self) -> None:
        if not self.touched:
            self.lustjinn.pop_screen()
            return

        async def throw_away() -> None:
            self.lustjinn.pop_screen()  # the confirm screen is gone by then; this one goes too

        self.lustjinn.push_screen(
            ConfirmScreen(
                "Cancel",
                "Throw away this new story?",
                ("Nothing has been created yet; what you typed here is lost.",),
                "Throw away",
                throw_away,
            )
        )

    def action_create(self) -> None:
        self.run_worker(self._create, exclusive=True)

    async def _create(self) -> None:
        character = self.character
        if character is None:
            self.status("The library has no characters yet. Add one first.", Kind.WARNING)
            return
        name = self.query_one("#name", Input).value.strip() or default_name(character.name)
        persona, model = self.persona, self.model
        started = await self.lustjinn.call(
            "Starting",
            self.lustjinn.api.create_story(
                name,
                character.id,
                persona_id=persona.id if persona is not None else None,
                model=model.id if model is not None else None,
            ),
        )
        if started is None:
            return
        self._open(started)

    def _open(self, story: Story) -> None:
        """Straight into the story. Creating one and then hunting for it in the list would be
        the terminal making the reader do its filing."""
        app = self.lustjinn
        app.pop_screen()
        opened = ConversationScreen(story)
        app.push_screen(opened)
        opened.call_after_refresh(opened.status, f'"{story.name}" started.', Kind.SUCCESS)
