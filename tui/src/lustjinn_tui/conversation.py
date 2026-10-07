"""The conversation: the screen the app exists for (``Views/ConversationView.cs``).

A centred reading column holds everything the screen owns: a header of one fact per line (where
the reader is, who is playing, what it has cost), the transcript, and the composer while it is
open. The column is three fifths of the window by default (``transcript_width_percent``), never
under forty columns, because past about ninety columns the eye loses the start of the next
line on the return sweep — a newspaper sets narrow columns on a wide page for the same reason.

A turn streams in: the reply grows under the character's name as the pieces arrive, the header
shows the phase and a clock, and the status row's spinner offers Esc to stop waiting. The draft
is cleared only once the server says it stored the message; a failed call never loses what was
typed.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import AsyncIterator
from functools import partial
from typing import ClassVar, Literal

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.content import Content
from textual.timer import Timer
from textual.widgets import Input, Static
from textual.worker import Worker

from lustjinn_tui import commands
from lustjinn_tui.api import (
    ApiError,
    AsideDone,
    Delta,
    Event,
    Failed,
    Message,
    Said,
    SignedOutError,
    Story,
    StorySpend,
    TurnDone,
    UnreachableError,
)
from lustjinn_tui.commands import Command, Commands, Incomplete, Prose, Unknown
from lustjinn_tui.completion import LIMIT, Completion, Offer, Strip
from lustjinn_tui.composer import Caption, Composer
from lustjinn_tui.confirm import ConfirmScreen
from lustjinn_tui.hairline import Hairline
from lustjinn_tui.legend import Hint
from lustjinn_tui.masthead import Masthead
from lustjinn_tui.panes import AskScreen, TextPaneScreen
from lustjinn_tui.regenerate import RegenerateScreen
from lustjinn_tui.settings import ChatSettingsScreen
from lustjinn_tui.status import Kind
from lustjinn_tui.textfmt import fit
from lustjinn_tui.transcript import Transcript
from lustjinn_tui.view import View

Mode = Literal["read", "write", "search", "branch"]

FLOOR = 40  # the column is never narrower than this, unless the window is


class ConversationScreen(View):
    HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("I / Enter", "Write a message"),
        Hint("↑↓", "Previous / next"),
        Hint("PgUp/PgDn", "Scroll"),
        Hint("/", "Search"),
        Hint(">", "Carry on"),
        Hint("G", "Regenerate reply"),
        Hint("S", "Settings"),
        Hint("B", "Branch from here"),
        Hint("Del", "Delete from here"),
        Hint("C", "Copy"),
        Hint("R", "Refresh"),
        Hint("Esc", "Back"),
    )
    WRITE_HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Send"),
        Hint("Alt+Enter", "New line"),
        Hint("Esc", "Cancel"),
    )
    SEARCH_HINTS: ClassVar[tuple[Hint, ...]] = (Hint("Enter", "Find"), Hint("Esc", "Cancel"))
    BRANCH_HINTS: ClassVar[tuple[Hint, ...]] = (
        Hint("Enter", "Create the branch"),
        Hint("Esc", "Cancel"),
    )
    AUTO_FOCUS: ClassVar[str | None] = ""
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "step(-1)", "Previous", show=False),
        Binding("down", "step(1)", "Next", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("i,I,enter", "write", "Write", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("n", "match(1)", "Next match", show=False),
        Binding("N", "match(-1)", "Previous match", show=False),
        Binding("greater_than_sign", "carry_on", "Carry on", show=False),
        Binding("g,G", "regenerate", "Regenerate", show=False),
        Binding("s,S", "settings", "Settings", show=False),
        Binding("b,B", "branch", "Branch", show=False),
        Binding("delete", "delete_from", "Delete from here", show=False),
        Binding("c,C", "copy", "Copy", show=False),
        Binding("r,R,ctrl+r", "refresh", "Refresh", show=False),
    ]

    DEFAULT_CSS = """
    ConversationScreen #body { align-horizontal: center; }
    ConversationScreen #column { height: 1fr; }
    ConversationScreen #header { height: auto; }
    ConversationScreen #column Input { }
    ConversationScreen .empty { color: $muted; }
    """

    def __init__(self, story: Story) -> None:
        super().__init__()
        self.story = story
        self.title = story.name
        self.messages: list[Message] = []
        self._mode: Mode = "read"
        self._query = ""
        self._spend: StorySpend | None = None
        self._persona_label = story.persona_name or "no persona"
        self._pending_label: str | None = None
        self._pending_since = 0.0
        self._clock: Timer | None = None
        self._turn: Worker[None] | None = None
        self._loaded = False
        self.commands = Commands()
        self._sent_command: str | None = None

    # -- the frame ------------------------------------------------------------------------------

    def hints(self) -> tuple[Hint, ...]:
        if self._mode == "write":
            return self.WRITE_HINTS
        if self._mode == "search":
            return self.SEARCH_HINTS
        if self._mode == "branch":
            return self.BRANCH_HINTS
        return self.HINTS

    def summary(self) -> str | None:
        position = self._position()
        if self._spend is not None and self._spend.calls:
            return f"{position} · ${self._spend.cost:.4f}"
        return position

    def body(self) -> ComposeResult:
        with Vertical(id="column"):
            yield Static("", id="header")
            yield Input(placeholder="search this story…", id="search", compact=True)
            yield Input(placeholder="name for the new story…", id="branch", compact=True)
            yield Hairline()
            yield Transcript(speaker=self.story.character_name, id="transcript")
            yield Hairline(id="composer-rule")
            yield Caption()
            yield Composer(id="composer")
            yield Strip()

    def on_mount(self) -> None:
        for selector in ("#search", "#branch", "#composer-rule", "Caption", "#composer", "Strip"):
            self.query_one(selector).display = False
        self.composer.providers.append(self._offer_commands)
        self._size_column()
        self._show_header()
        self.run_worker(partial(self._load, "Loading the story"), exclusive=True)
        self.run_worker(self._read_commands, exclusive=False)

    async def _read_commands(self) -> None:
        """The server's list wins over the shipped one whenever it can be read."""
        with contextlib.suppress(ApiError, UnreachableError):
            self.commands = Commands(await self.lustjinn.api.commands())

    def on_resize(self) -> None:
        self._size_column()

    def _size_column(self) -> None:
        """Three fifths (the config's share, 30-100) of the window, centred; a window under the
        floor gets all of itself."""
        share = max(30, min(100, self.lustjinn.config.transcript_width_percent))
        width = self.lustjinn.size.width
        wanted = width * share // 100
        self.query_one("#column").styles.width = max(min(FLOOR, width), min(wanted, width))

    @property
    def transcript(self) -> Transcript:
        return self.query_one("#transcript", Transcript)

    @property
    def composer(self) -> Composer:
        return self.query_one("#composer", Composer)

    @property
    def selected(self) -> Message | None:
        return self.transcript.selected_message

    # -- loading --------------------------------------------------------------------------------

    async def _load(self, label: str) -> None:
        api = self.lustjinn.api
        read = await self.lustjinn.call(label, api.story(self.story.id))
        if read is None:
            return
        self.story = read
        self.title = read.name
        self.lustjinn.model_name = read.model or ""
        self.query_one(Masthead).set_model(self.lustjinn.model_name)
        self.messages = read.messages
        self.transcript.show(self.messages, land=True)
        if read.persona_name is None:
            try:
                defaults = await api.defaults()
            except ApiError, UnreachableError:
                defaults = None
            if defaults is not None and defaults.default_persona_name:
                self._persona_label = f"{defaults.default_persona_name} (the default)"
        await self._refresh_spend()
        self._loaded = True
        self._show_header()
        yours = sum(1 for m in self.messages if m.role == "user")
        replies = sum(1 for m in self.messages if m.role == "assistant")
        self.status(f"{yours} from you, {replies} replies.", Kind.SUCCESS)

    async def _refresh_spend(self) -> None:
        """Never allowed to break the screen it decorates: a ledger that cannot be read is a
        header without a figure on it."""
        try:
            self._spend = await self.lustjinn.api.story_spend(self.story.id)
        except ApiError, UnreachableError:
            self._spend = None
        self._show_header()

    # -- the header -----------------------------------------------------------------------------

    def _position(self) -> str:
        transcript = self.transcript
        return "—" if not transcript.turns else f"{transcript.selected + 1}/{transcript.turns}"

    def _header_lines(self) -> list[str]:
        """One fact per line; a line with nothing to say is dropped rather than left blank."""
        lines: list[str] = []
        if self._pending_label is not None:
            elapsed = time.monotonic() - self._pending_since
            clock = f" — {elapsed:.0f}s" if elapsed >= 1 else ""
            lines.append(f"[$warning]{Content(self._pending_label).markup}{clock}…[/]")
        else:
            selected = self.selected
            words = len(selected.text.split()) if selected is not None else 0
            yours = sum(1 for m in self.messages if m.role == "user")
            replies = sum(1 for m in self.messages if m.role == "assistant")
            facts = f"  ·  {yours} yours  ·  {replies} replies  ·  {words} words in this one"
            if self._query:
                facts += f'  ·  filter "{Content(self._query).markup}"'
            lines.append(f"[$accent]message {self._position()}[/][$muted]{facts}[/]")
        if self._loaded:
            who = Content(self.story.character_name).markup
            as_whom = Content(self._persona_label).markup
            lines.append(f"[$muted]{who}  ·  as {as_whom}[/]")
        spend = self._spend
        if spend is not None and spend.calls:
            line = f"[$warning]${spend.cost:.4f}[/]"
            if spend.discarded_cost > 0:
                line += f"  [$muted](${spend.discarded_cost:.4f} rerolled away)[/]"
            lines.append(line)
        return lines

    def _show_header(self) -> None:
        self.query_one("#header", Static).update(
            Content.from_markup("\n".join(self._header_lines()))
        )

    @on(Transcript.Moved)
    def _moved(self) -> None:
        self._show_header()

    # -- reading --------------------------------------------------------------------------------

    def action_step(self, direction: int) -> None:
        self.transcript.step(direction)

    def action_page(self, direction: int) -> None:
        self.transcript.page(direction)

    def action_first(self) -> None:
        self.transcript.first()

    def action_last(self) -> None:
        self.transcript.last()

    def action_refresh(self) -> None:
        self.run_worker(partial(self._load, "Loading the story"), exclusive=True)

    def action_copy(self) -> None:
        message = self.selected
        if message is None:
            self.status("Select a message first.", Kind.WARNING)
            return
        self.lustjinn.copy_to_clipboard(message.text)
        self.status("Message copied to the clipboard.", Kind.SUCCESS)

    def action_back(self) -> None:
        if self._pending_label is not None:
            self._stop_waiting()
        elif self._mode == "write":
            self._close_composer()
        elif self._mode == "search":
            self._leave_search(clear=True)
        elif self._mode == "branch":
            self._leave_branch()
            self.status("Branch cancelled.")
        elif self._query:
            self._query = ""
            self.transcript.search("")
            self._show_header()
            self.status("Filter cleared.")
        else:
            self.lustjinn.go_back()

    # -- writing --------------------------------------------------------------------------------

    def action_write(self) -> None:
        if self._mode != "read":
            return
        self._mode = "write"
        for selector in ("#composer-rule", "Caption", "#composer"):
            self.query_one(selector).display = True
        self._measure_draft()
        self.composer.focus()
        self.refresh_hints()
        self.status("Type your message. Enter sends it.")

    def _close_composer(self) -> None:
        self._mode = "read"
        for selector in ("#composer-rule", "Caption", "#composer"):
            self.query_one(selector).display = False
        self.composer.dismiss_offers()
        self.set_focus(None)
        self.refresh_hints()
        if self.composer.text:
            self.status("Draft kept. Press I to carry on writing.")

    @on(Composer.Changed)
    def _draft_changed(self) -> None:
        self._measure_draft()

    def _measure_draft(self) -> None:
        self.query_one(Caption).measure(self.composer.text)

    @on(Composer.Offered)
    def _offered(self, event: Composer.Offered) -> None:
        strip = self.query_one(Strip)
        strip.show(event.offer)
        strip.index = self.composer.choice
        strip.refresh()

    def _offer_commands(self, line: str, column: int, first_line: bool) -> Offer | None:
        """A command name being typed wins over everything, and only in the one place a
        command can start: the very first character of the message."""
        typed = commands.command_being_typed(line, column, first_line=first_line)
        if typed is None:
            return None
        found = self.commands.matching(typed)[:LIMIT]
        if not found:
            return None
        return Offer(
            0,
            len(typed) + 1,
            tuple(Completion(f"/{spec.name}", f"/{spec.name} ") for spec in found),
        )

    @on(Composer.Send)
    def _send(self) -> None:
        text = self.composer.text.strip()
        if not text:
            self.status("Nothing to send.", Kind.WARNING)
            return
        self.dispatch(text)

    def dispatch(self, text: str) -> None:
        """Runs whatever the composer turned out to hold: a message, a command, or a refusal."""
        match self.commands.parse(text):
            case Prose():
                # As typed, a doubled slash included: the API strips it the same way, and the
                # hash that makes a retry one turn is over what it received.
                self._sent_command = None
                self.send(text)
            case Unknown(name=name):
                # Refused rather than sent. A typo would otherwise cost what the message it was
                # meant to be would have cost, and land in the story as a line the character
                # has to react to — which append-only means nobody can take back.
                self.status(
                    f"There is no /{name} command. Type /help for the list, or //{name} to "
                    "send it as a message.",
                    Kind.WARNING,
                )
            case Incomplete(spec=spec):
                self.status(f"{spec.usage} — nothing has been sent.", Kind.WARNING)
            case Command(spec=spec, argument=argument, local=True):
                # A free command's draft goes now; a billed or writing one keeps it until the
                # work has landed: re-typing /facts costs a second, re-typing the question a
                # failed /ask ate costs the reader the thought behind it.
                self.composer.clear()
                self._measure_draft()
                self._close_composer()
                self.run_worker(partial(self._report, spec.name, argument), exclusive=True)
            case Command(spec=spec, argument=argument):
                self._sent_command = spec.name
                if spec.cost == "free":
                    self.composer.clear()
                    self._measure_draft()
                self.send(text)

    def send(self, text: str) -> None:
        """Sends ``text`` — a message or an API command — and streams what comes back."""
        self._close_composer()
        self._begin_turn("Sending", self.lustjinn.api.send(self.story.id, text))

    async def _report(self, name: str, argument: str) -> None:
        """The reading commands, answered from the API's GET endpoints and shown in a pane, or
        a status when there is nothing to show."""
        api = self.lustjinn.api
        story = self.story
        report: commands.Report | None = None
        if name == "card":
            card = await self.lustjinn.call(
                "Reading the card", api.entry("characters", story.character_id)
            )
            if card is None:
                return
            report = commands.page_report("Character", card.text, "This story has no character.")
        elif name == "persona":
            persona_id = story.persona_id
            if persona_id is None:
                defaults = await self.lustjinn.call("Reading the persona", api.defaults())
                if defaults is None:
                    return
                persona_id = defaults.default_persona_id
            text = None
            if persona_id is not None:
                persona = await self.lustjinn.call(
                    "Reading the persona", api.entry("personas", persona_id)
                )
                if persona is None:
                    return
                text = persona.text
            report = commands.page_report("Persona", text, "This story has no persona.")
        elif name == "facts":
            facts = await self.lustjinn.call("Facts", api.facts(story.id, all=True))
            if facts is None:
                return
            report = commands.facts_report(facts)
        elif name == "trackers":
            meters = await self.lustjinn.call("Trackers", api.trackers(story.id))
            if meters is None:
                return
            report = commands.trackers_report(meters)
        elif name == "audit":
            audit = await self.lustjinn.call("Audit", api.audit(story.id))
            if audit is None:
                return
            report = commands.audit_report(audit)
        elif name == "cost":
            await self._refresh_spend()  # the header's figure comes up to date with the pane
            report = commands.cost_report(self._spend)
        elif name == "search":
            self._find(argument)
            return
        elif name == "help":
            report = commands.Report(
                "Commands", "typed in the composer", tuple(self.commands.help_lines())
            )
        if report is None:
            return
        if report.is_empty:
            self.status(report.subtitle)
        else:
            self.lustjinn.push_screen(TextPaneScreen(report))

    def _find(self, query: str) -> None:
        """``/search`` runs the in-story search that ``/`` in reading mode opens."""
        self._query = query
        self.transcript.search(query)
        self._show_header()
        hits = sum(1 for m in self.messages if query.lower() in m.text.lower())
        if hits == 0:
            self._query = ""
            self.transcript.search("")
            self._show_header()
            self.status(f'"{query}" is not in this story.', Kind.WARNING)
            return
        self.action_match(1)
        self.status(f"{hits} message(s) match. n for the next one.", Kind.SUCCESS)

    def action_carry_on(self) -> None:
        """No confirmation, deliberately: a prompt before every continuation would make the one
        thing this is for — reading on — tedious. The status row says it spends."""
        if self._mode != "read":
            return
        if not any(m.role == "assistant" for m in self.messages):
            self.status("There is no reply to carry on from yet.", Kind.WARNING)
            return
        self._begin_turn("Continuing", self.lustjinn.api.carry_on(self.story.id))

    def action_regenerate(self) -> None:
        if self._mode != "read":
            return
        if not self.messages or self.messages[-1].role != "assistant":
            self.status("There is no reply to regenerate yet.", Kind.WARNING)
            return
        last = self.messages[-1]
        if last.model is None and not any(m.role == "user" for m in self.messages):
            self.status(
                "The opening is not rerolled: a person wrote it. Write your first turn; the "
                "reply to it can be rerolled."
            )
            return
        self.lustjinn.push_screen(RegenerateScreen(last, self.regenerate))

    def action_settings(self) -> None:
        if self._mode != "read":
            return
        self.lustjinn.push_screen(ChatSettingsScreen(self.story, self._model_changed))

    def _model_changed(self, model: str | None) -> None:
        """The settings changed the story's model: the masthead says so from now on."""
        self.story = self.story.model_copy(update={"model": model})
        self.lustjinn.model_name = model or ""
        self.query_one(Masthead).set_model(self.lustjinn.model_name)

    def regenerate(self, reason: str, instructions: str | None) -> None:
        replacing = self.messages[-1].id
        self._begin_turn(
            "Regenerating",
            self.lustjinn.api.reroll(self.story.id, reason, instructions),
            replacing=replacing,
        )

    # -- a turn in flight -----------------------------------------------------------------------

    def _begin_turn(
        self, label: str, stream: AsyncIterator[Event], *, replacing: uuid.UUID | None = None
    ) -> None:
        self._turn = self.run_worker(
            partial(self._run, label, stream, replacing), exclusive=True, group="turn"
        )

    async def _run(
        self, label: str, stream: AsyncIterator[Event], replacing: uuid.UUID | None
    ) -> None:
        transcript = self.transcript
        if replacing is not None:
            # Replaced, not merged: the reply that was there is gone from the screen before the
            # new one starts, or the two wordings would sit side by side.
            self.messages = [m for m in self.messages if m.id != replacing]
            transcript.show(self.messages, land=False)
        self._pending_label, self._pending_since = label, time.monotonic()
        self._clock = self.set_interval(1.0, self._show_header)
        self.status_line.busy(label)
        transcript.begin_pending()
        self._show_header()
        try:
            async for event in stream:
                if isinstance(event, Delta):
                    transcript.grow_pending(event.text)
                elif isinstance(event, TurnDone):
                    self._arrived(event)
                elif isinstance(event, Failed):
                    self._failed(event)
                elif isinstance(event, AsideDone):
                    self._answered(event)
                else:
                    self._said(event)
        except SignedOutError as refused:
            self.lustjinn.signed_out(refused.detail)
        except UnreachableError:
            self.lustjinn.lost(f"The server stopped answering while {label.lower()}.")
        except ApiError as refused:
            self.status(refused.detail, Kind.ERROR)
        finally:
            self._end_turn()

    def _end_turn(self) -> None:
        self._pending_label = None
        if self._clock is not None:
            self._clock.stop()
            self._clock = None
        self.status_line.idle()
        self.transcript.end_pending()
        self._show_header()

    def _arrived(self, done: TurnDone) -> None:
        added = [m for m in (done.sent, done.reply) if m is not None]
        known = {m.id for m in self.messages}
        self.messages = [*self.messages, *(m for m in added if m.id not in known)]
        self.composer.clear()
        self._measure_draft()
        self.transcript.end_pending()
        self.transcript.show(self.messages, land=True)
        if done.reply.fell_back_from:
            self.status(
                f"{done.reply.fell_back_from} could not write this reply (not available, or the "
                "story no longer fits it), so the default did. S to change.",
                Kind.WARNING,
            )
        elif done.replayed:
            self.status("That message had been sent before; here is its reply.")
        else:
            self.status("Reply received.", Kind.SUCCESS)
        self.run_worker(self._refresh_spend, exclusive=False)

    def _answered(self, done: AsideDone) -> None:
        """A question answered out of character: the draft goes only now — a question that
        failed is one the reader would have to type again, and it was theirs."""
        self.composer.clear()
        self._measure_draft()
        self.transcript.end_pending()
        self.run_worker(self._refresh_spend, exclusive=False)
        self.lustjinn.push_screen(AskScreen(self.story.id, self.story.character_name, done.aside))

    def _said(self, said: Said) -> None:
        """A command that answers in words and stores no turn: a recap gets a pane, a write
        gets the status row."""
        self.composer.clear()
        self._measure_draft()
        self.transcript.end_pending()
        if self._sent_command == "recap":
            self.lustjinn.push_screen(
                TextPaneScreen(
                    commands.Report(
                        "Recap", "nothing stored, nothing billed", tuple(said.text.splitlines())
                    )
                )
            )
        else:
            self.status(said.text, Kind.SUCCESS)

    def _failed(self, failed: Failed) -> None:
        """The model did not answer. The reader's message, when it was stored, is in the
        transcript now and the draft goes; otherwise the draft stays for another try."""
        if failed.sent is not None and all(m.id != failed.sent.id for m in self.messages):
            self.messages = [*self.messages, failed.sent]
            self.composer.clear()
            self._measure_draft()
        self.transcript.end_pending()
        self.transcript.show(self.messages, land=True)
        self.status(failed.detail, Kind.ERROR)

    def _stop_waiting(self) -> None:
        """Stopped after the server took the message: not an un-send. The reply may still be
        written; a refresh finds it rather than a second Enter sending it again."""
        if self._turn is not None:
            self._turn.cancel()
            self._turn = None
        self._end_turn()
        self.status(
            "Stopped waiting. Your message was already sent — press R to refresh for the "
            "reply rather than sending it again.",
            Kind.WARNING,
        )

    # -- searching ------------------------------------------------------------------------------

    def action_search(self) -> None:
        if self._mode != "read":
            return
        self._mode = "search"
        field = self.query_one("#search", Input)
        field.value = self._query
        self.query_one("#header").display = False
        field.display = True
        field.focus()
        self.refresh_hints()

    @on(Input.Submitted, "#search")
    def _searched(self, event: Input.Submitted) -> None:
        self._leave_search(clear=False)
        self._query = event.value
        self.transcript.search(self._query)
        self._show_header()
        if not self._query:
            return
        hits = sum(1 for m in self.messages if self._query.lower() in m.text.lower())
        if hits == 0:
            self.status(f'"{self._query}" is not in this story.', Kind.WARNING)
            return
        self.action_match(1)
        self.status(f"{hits} message(s) match.", Kind.SUCCESS)

    def _leave_search(self, *, clear: bool) -> None:
        self._mode = "read"
        self.query_one("#search", Input).display = False
        self.query_one("#header").display = True
        self.set_focus(None)
        if clear:
            self._query = ""
            self.transcript.search("")
            self._show_header()
        self.refresh_hints()

    def action_match(self, delta: int) -> None:
        if self._mode != "read":
            return
        if not self._query or not self.messages:
            self.status("No active search.", Kind.WARNING)
            return
        count = len(self.messages)
        selected = self.transcript.selected
        needle = self._query.lower()
        for offset in range(1, count + 1):
            index = (selected + delta * offset) % count
            if needle in self.messages[index].text.lower():
                self.transcript.land(index)
                return
        self.status("No further matches.", Kind.WARNING)

    # -- branching ------------------------------------------------------------------------------

    def action_branch(self) -> None:
        """Branching keeps everything and destroys nothing, so it is a plain letter and asks for
        a name, not a confirmation: the worst outcome of a mistake is one extra story."""
        if self._mode != "read":
            return
        if self.selected is None:
            self.status("Select the turn to branch from first.", Kind.WARNING)
            return
        self._mode = "branch"
        field = self.query_one("#branch", Input)
        field.value = f"{self.story.name} (2)"
        field.placeholder = f"Branch at message {self._position()} — name"
        self.query_one("#header").display = False
        field.display = True
        field.focus()
        self.refresh_hints()

    @on(Input.Submitted, "#branch")
    def _branch_named(self, event: Input.Submitted) -> None:
        name = event.value.strip() or None
        message = self.selected
        self._leave_branch()
        if message is None:
            return
        self.run_worker(partial(self._branch, message, name), exclusive=True)

    async def _branch(self, message: Message, name: str | None) -> None:
        copy = await self.lustjinn.call(
            "Branching", self.lustjinn.api.branch(self.story.id, message.id, name)
        )
        if copy is not None:
            self.status(f'Branched as "{copy.name}": it is in the list of stories.', Kind.SUCCESS)

    def _leave_branch(self) -> None:
        self._mode = "read"
        self.query_one("#branch", Input).display = False
        self.query_one("#header").display = True
        self.set_focus(None)
        self.refresh_hints()

    # -- deleting from here ---------------------------------------------------------------------

    def action_delete_from(self) -> None:
        if self._mode != "read":
            return
        target = self.selected
        if target is None:
            self.status("Select a message first.", Kind.WARNING)
            return
        index = next(i for i, m in enumerate(self.messages) if m.id == target.id)
        doomed = len(self.messages) - index
        preview = fit(target.text.replace("\n", " "), 60)

        async def delete() -> None:
            cut = await self.lustjinn.api.delete_from(self.story.id, target.id)
            self.messages = cut.story.messages
            self.transcript.show(self.messages, land=True)
            self.status(
                f"Deleted {cut.hidden} message(s). {len(self.messages)} remain.", Kind.SUCCESS
            )
            await self._refresh_spend()

        self.lustjinn.push_screen(
            ConfirmScreen(
                "Delete",
                f"Delete this message and the {doomed - 1} after it?",
                (
                    f"From: {preview}",
                    "",
                    f"{doomed} message(s) would be removed from the story itself, not just from "
                    "this client, with the memory those turns built.",
                    "This cannot be undone.",
                    "",
                    f"{index} message(s) would remain.",
                ),
                "Delete",
                delete,
            )
        )
