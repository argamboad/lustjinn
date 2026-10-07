"""The composer's slash commands, decided before anything is sent (``SlashCommands.cs``,
``ConversationView.Commands.cs``, ``StoryReports.cs``).

A message is permanent and billed. ``(OOC: skip to the evening)`` typed into the composer reaches
the model, is stored for good, is counted in every later prompt and may be summarised as
something that happened. A command routes the same words where they belong — or nowhere — and
leaves the transcript alone. So an unrecognised command is **refused, never sent**: the API would
refuse it too (#18), but the client refuses first so that no request is made at all.

Two kinds live side by side. The API's own commands (``/do``, ``/focus``, ``/ask``, ``/recap``,
``/fact``, ``/tracker``) go to the server as typed and come back as a stream; the reading
commands (``/card``, ``/persona``, ``/facts``, ``/trackers``, ``/audit``, ``/cost``,
``/search``, ``/help``) are the client's, answered from the API's GET endpoints and shown in a
pane. ``//`` sends a line that genuinely starts with a slash.

The report builders turn what the API answered into lines a pane shows, the donor's wording
kept, so "the facts" or "what this story has cost" reads the same here and on the phone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from typing import Final, Literal

from lustjinn_tui.api import Audit, Fact, Hit, Spec, StorySpend, Tracker

Cost = Literal["free", "billed", "write"]

LOCAL: Final[tuple[Spec, ...]] = (
    Spec(
        name="card",
        usage="/card",
        summary="The character's card, as every prompt carries it",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="persona",
        usage="/persona",
        summary="Who you are in this story: the persona every prompt carries",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="facts",
        usage="/facts",
        summary="What is true right now: the live facts, by subject",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="trackers",
        usage="/trackers",
        summary="The story's meters and where they stand",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="audit",
        usage="/audit",
        summary="What the recent replies were built from and what each cost",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="cost",
        usage="/cost",
        summary="What this story has cost, by kind of call",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="search",
        usage="/search <words>",
        summary="Find words in this story; n and N step through the matches",
        cost="free",
    ),
    Spec(
        name="help",
        usage="/help",
        summary="Every command, with what each one costs",
        cost="free",
        needs_argument=False,
    ),
)

# The API's list, as it stood when this was built: used until GET /commands answers, and when
# it cannot. The server's list wins whenever it is read, so the two never drift for long.
SHIPPED: Final[tuple[Spec, ...]] = (
    Spec(
        name="do",
        usage="/do <direction>",
        summary="Steer the next reply with an out-of-character direction; with a blank line "
        "and a message under it, the message is sent and the direction steers the reply",
        cost="billed",
    ),
    Spec(
        name="focus",
        usage="/focus <who>",
        summary="Hand the next reply to a named character",
        cost="billed",
    ),
    Spec(
        name="ask",
        usage="/ask <question>",
        summary="Ask about the story out of character; the answer is shown, never stored",
        cost="billed",
    ),
    Spec(
        name="recap",
        usage="/recap [turns]",
        summary="The story so far: the latest summary, then the last few turns word for word",
        cost="free",
        needs_argument=False,
    ),
    Spec(
        name="fact",
        usage="/fact <statement>",
        summary="Pin something as true from now on, under the character's name",
        cost="write",
    ),
    Spec(
        name="tracker",
        usage="/tracker <name> <value>",
        summary="Set a meter by hand; the value is the last word",
        cost="write",
    ),
)


@dataclass(frozen=True, slots=True)
class Prose:
    """Ordinary words: send them."""

    text: str


@dataclass(frozen=True, slots=True)
class Command:
    spec: Spec
    argument: str
    local: bool
    """Answered here from a GET, rather than sent to ``/send``."""


@dataclass(frozen=True, slots=True)
class Unknown:
    name: str


@dataclass(frozen=True, slots=True)
class Incomplete:
    spec: Spec


Parsed = Prose | Command | Unknown | Incomplete


class Commands:
    """What the composer knows: the server's commands and the client's own."""

    def __init__(self, remote: Sequence[Spec] = SHIPPED) -> None:
        self.remote = tuple(remote)

    @property
    def all(self) -> tuple[Spec, ...]:
        return self.remote + LOCAL

    def find(self, name: str) -> tuple[Spec, bool] | None:
        wanted = name.lower()
        for spec in self.remote:
            if spec.name == wanted:
                return spec, False
        for spec in LOCAL:
            if spec.name == wanted:
                return spec, True
        return None

    def matching(self, prefix: str) -> list[Spec]:
        """The commands whose name starts with ``prefix``, in the help's order."""
        wanted = prefix.lower()
        return [spec for spec in self.all if spec.name.startswith(wanted)]

    def parse(self, text: str) -> Parsed:
        """The API's rule (``lustjinn.commands.parse``): only a slash in the very first column
        counts; the name runs to the first whitespace, a newline included."""
        composed = text.strip()
        if not composed.startswith("/"):
            return Prose(composed)
        if composed.startswith("//"):
            return Prose(composed[1:])
        typed = composed[1:]
        end = 0
        while end < len(typed) and not typed[end].isspace():
            end += 1
        name, argument = typed[:end], typed[end:].strip()
        found = self.find(name)
        if found is None:
            return Unknown(name)
        spec, local = found
        if spec.needs_argument and not argument:
            return Incomplete(spec)
        return Command(spec, argument, local)

    def help_lines(self) -> list[str]:
        """The donor's ``/help``: grouped by cost, usage then summary, the doubled slash last."""
        headings = {
            "billed": "Billed — these call the model",
            "write": "These write to the story",
            "free": "Free — these only read what is already here",
        }
        lines: list[str] = []
        for cost in ("billed", "write", "free"):
            group = [spec for spec in self.all if spec.cost == cost]
            if not group:
                continue
            lines.append(headings[cost])
            for spec in group:
                lines.append(f"  {spec.usage}")
                lines.append(f"      {spec.summary}")
            lines.append("")
        lines.append(
            "A message that genuinely starts with a slash is sent by doubling it: //like this."
        )
        return lines


def command_being_typed(line: str, column: int, *, first_line: bool) -> str | None:
    """The command name under the caret, when it is inside one: only on the first line, only
    from the first column, and only while no space has been typed yet — past the space the
    reader is writing the argument. A doubled slash is the escape for prose, not a command."""
    if not first_line or not line or line[0] != "/" or column < 1:
        return None
    if len(line) > 1 and line[1] == "/":
        return None
    typed = line[1 : min(column, len(line))]
    return None if any(c.isspace() for c in typed) else typed


# -- the panes' lines -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """A page of text: what it is, a line about it (or, when there are no lines, why there is
    nothing), and the body."""

    title: str
    subtitle: str
    lines: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.lines


def facts_report(facts: Sequence[Fact]) -> Report:
    live = [f for f in facts if f.valid_to_sequence is None]
    if not live:
        return Report(
            "Facts", "Nothing is being injected as true yet. /fact <statement> writes one."
        )
    lines: list[str] = []
    for subject, group in groupby(sorted(live, key=lambda f: f.subject), key=lambda f: f.subject):
        lines.append(subject)
        for fact in sorted(group, key=lambda f: f.valid_from_sequence):
            lines.append(f"  · {fact.text}" + ("  (pinned)" if fact.pinned else ""))
        lines.append("")
    retired = len(facts) - len(live)
    subtitle = f"{len(live)} live, {retired} retired" if retired else f"{len(live)} live"
    return Report("Facts", subtitle, tuple(lines))


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def trackers_report(meters: Sequence[Tracker]) -> Report:
    if not meters:
        return Report("Trackers", "This story keeps no meters. /tracker <name> <value> starts one.")
    lines: list[str] = []
    for meter in meters:
        line = f"{meter.name}  {_number(meter.value)} / {_number(meter.max)}"
        if meter.delta:
            line += f"   last moved {meter.delta:+.2f}".rstrip("0").rstrip(".")
        lines.append(line)
        if meter.note and meter.note.strip():
            lines.append(f"  {meter.note}")
        lines.append("")
    return Report("Trackers", f"{len(meters)} meter(s)", tuple(lines))


def _count(tokens: int | None) -> str:
    return "?" if tokens is None else f"{tokens:,}"


def audit_report(audit: Audit) -> Report:
    if not audit.turns and not audit.asides:
        return Report("Audit", "Nothing has been generated in this story yet.")
    lines: list[str] = []
    for turn in audit.turns:
        hidden = "  (rolled back)" if turn.hidden else ""
        lines.append(
            f"#{turn.sequence}{hidden}   {_count(turn.prompt_tokens)} in, "
            f"{_count(turn.completion_tokens)} out   served by {turn.provider or 'unknown'}"
        )
        if turn.context and turn.context.strip():
            lines.append(f"  {turn.context}")
        lines.append("")
    if audit.asides:
        lines.append("Questions asked out of character")
        for aside in audit.asides:
            lines.append(
                f"  · #{aside.sequence}   {_count(aside.prompt_tokens)} in, "
                f"{_count(aside.completion_tokens)} out   served by {aside.provider or 'unknown'}"
            )
    subtitle = f"{len(audit.turns)} turn(s)"
    if audit.asides:
        subtitle += f", {len(audit.asides)} question(s)"
    return Report("Audit", subtitle, tuple(lines))


KIND_NAMES: Final[dict[str, str]] = {
    "reply": "replies",
    "aside": "questions",
    "summary": "compression",
    "facts": "extraction",
}


def cost_report(spend: StorySpend | None) -> Report:
    if spend is None or not spend.calls:
        return Report("Cost", "Nothing has been spent on this story yet.")
    lines = [f"${spend.cost:.4f}   over {spend.calls} billed call(s)", ""]
    for kind in spend.by_kind:
        name = KIND_NAMES.get(kind.kind, kind.kind)
        lines.append(f"  {name:<14}${kind.cost:.4f}   {kind.calls} call(s)")
    lines.append("")
    lines.append(f"  {'tokens':<14}{spend.prompt_tokens:,} in, {spend.completion_tokens:,} out")
    if spend.cached_share is not None:
        lines.append(
            f"  {'cached':<14}{spend.cached_share:.0%} of the prompt was served from cache"
        )
    else:
        lines.append(f"  {'cached':<14}the provider never said")
    if spend.discarded_cost > Decimal(0):
        lines.append("")
        lines.append(
            f"  ${spend.discarded_cost:.4f} went on {spend.discarded_calls} reply(ies) you "
            "regenerated or cut away. They are still in the audit."
        )
    if spend.unpriced:
        lines.append("")
        lines.append(f"  {spend.unpriced} call(s) came back with no price, so this is a floor.")
    lines.append("")
    lines.append("  Embeddings are not counted; the whole corpus costs under a cent.")
    return Report("Cost", spend.name, tuple(lines))


def search_report(hits: Sequence[Hit], query: str, speaker: str) -> Report:
    wanted = query.strip()
    found = [hit for hit in hits if hit.scope == "message"]
    if not found:
        return Report("Search", f'"{wanted}" is not in this story.')
    lines = [
        f"#{hit.sequence} {'You' if hit.role == 'user' else hit.speaker or speaker}: {hit.snippet}"
        for hit in found
    ]
    return Report("Search", f'{len(found)} turn(s) with "{wanted}"', tuple(lines))


def page_report(title: str, text: str | None, missing: str) -> Report:
    """A card or a persona, whole: one paragraph per line."""
    if text is None or not text.strip():
        return Report(title, missing)
    return Report(title, "as every prompt carries it", tuple(text.strip().splitlines()))
