"""Slash commands: what the composer's text turns out to be, decided before anything is sent.

A message is permanent and billed. `(OOC: skip to the evening)` typed into one reaches the model,
is stored forever, is counted in every later prompt and may be summarised as something that
happened. A command routes the same words where they belong — or nowhere — and leaves the
transcript alone. So an unrecognised command is refused, never sent: a typo would otherwise cost
what the message would have cost and land in the story as nonsense the character has to react
to. Prose that genuinely starts with a slash is sent by doubling it.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Spec:
    """One command the API recognises."""

    name: str
    usage: str
    summary: str
    cost: Literal["free", "billed", "write"]
    """What it costs the reader, which is the first thing they want to know: nothing, a model
    call, or a write to the story's own state."""
    needs_argument: bool = True


# In the order a help listing shows them. Each later step adds its commands as it builds them;
# until then they are unknown here, and refused.
COMMANDS: tuple[Spec, ...] = (
    Spec(
        "ask",
        "/ask <question>",
        "Ask about the story out of character. The answer is shown, never stored in the story",
        "billed",
    ),
)


@dataclass(frozen=True)
class Prose:
    """Ordinary words: send them."""

    text: str


@dataclass(frozen=True)
class Command:
    """A command the API knows, with whatever followed it."""

    spec: Spec
    argument: str


@dataclass(frozen=True)
class Unknown:
    """Something that looks like a command and is not one. Refuse it."""

    name: str


@dataclass(frozen=True)
class Incomplete:
    """A command that needs an argument, typed without one. Refuse it, quoting the usage."""

    spec: Spec


Parsed = Prose | Command | Unknown | Incomplete


def find(name: str) -> Spec | None:
    return next((c for c in COMMANDS if c.name == name.lower()), None)


def parse(text: str) -> Parsed:
    """Reads what was typed. Only a slash in the very first column counts: a slash anywhere
    else is punctuation (and/or, a date), and prose is far more common than commands."""
    composed = text.strip()
    if not composed.startswith("/"):
        return Prose(composed)
    # A doubled slash is how prose that genuinely opens with one is sent. Stripping the first
    # is the whole of it: what remains is never looked at again for commands.
    if composed.startswith("//"):
        return Prose(composed[1:])
    # The name runs to the first whitespace, a newline included: a command whose argument
    # begins on the next line is still that command.
    typed = composed[1:]
    end = 0
    while end < len(typed) and not typed[end].isspace():
        end += 1
    name, argument = typed[:end], typed[end:].strip()
    spec = find(name)
    if spec is None:
        return Unknown(name)
    if spec.needs_argument and not argument:
        return Incomplete(spec)
    return Command(spec, argument)
