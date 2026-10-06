"""The context builder: what the model is sent, assembled from layers in a fixed order.

The order is least volatile first — character, persona, directives, world, summaries, history,
recalled memories, trackers, instruction — because a provider's prefix cache keeps everything up
to the first byte that changed. The card never changes; the instruction changes every turn. Put
retrieval in the middle and the cache would break on every turn.

Pure functions over dataclasses: nothing here touches the database or the network, so every rule
is tested with a real-size card in a few milliseconds.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from lustjinn.models import Character, Message, Persona, Role
from lustjinn.openrouter import ChatMessage

PERSONA_FRAME = (
    "The user is playing the following person. Speak to them as this person, and never write "
    "their words or actions for them.\n\n"
)
WORLD_FRAME = "What is true in this story right now:\n"
MEMORIES_FRAME = "Earlier in this conversation:\n"


def ask_directive(question: str) -> str:
    """The instruction for a question asked out of character. Like every instruction sent, it
    says what it is — not a turn — and what the reply must be: an answer, from what was given."""
    return (
        "Step out of the scene. This is a question from the reader about the story, put to you "
        "as its author, and it is not a turn: nothing here is said aloud by anyone and nothing "
        "that follows happens.\n\n"
        "Answer in your own voice, briefly and plainly. No prose, no dialogue, no action, no "
        "staying in character, and do not move the story forward by so much as a moment.\n\n"
        "Answer only from what you have been given above. Where it does not say, say that it "
        "does not say. Anything you make up here is written down nowhere and will be gone the "
        "moment this is read, so an invented detail becomes something the reader believes and "
        "the story then contradicts.\n\n"
        f"The question: {question.strip()}"
    )


@dataclass(frozen=True)
class Fact:
    """Something true in the story right now. Step 6 extracts them; step 7 lets a person add one."""

    subject: str
    text: str


@dataclass(frozen=True)
class Recalled:
    """A turn brought back by retrieval (step 6): already summarised away, relevant again."""

    sequence: int
    role: Role
    text: str


def reader_name(persona: Persona | None) -> str:
    """How the reader is named in anything a model reads. Never "User": a model told about
    "User" writes a story with a user in it."""
    return persona.name if persona is not None else "the reader"


def world_layer(facts: Sequence[Fact]) -> str | None:
    if not facts:
        return None
    return WORLD_FRAME + "\n".join(f"{fact.subject}: {fact.text}" for fact in facts)


def memories_layer(
    recalled: Sequence[Recalled], character: Character, persona: Persona | None
) -> str | None:
    """Recalled turns as a dated transcript, so the model knows they are from earlier."""
    if not recalled:
        return None
    who = {Role.ASSISTANT: character.name, Role.USER: reader_name(persona), Role.SYSTEM: "Note"}
    lines = [f"[{turn.sequence}] {who[turn.role]}: {turn.text}" for turn in recalled]
    return MEMORIES_FRAME + "\n".join(lines)


@dataclass(frozen=True, kw_only=True)
class Layers:
    """Everything a prompt may be built from. Keyword-only on purpose: three bugs in the donor
    came from a positional layer added in the middle of an argument list."""

    character: Character
    persona: Persona | None = None
    directives: str | None = None
    """The dials, rendered (step 7)."""
    facts: Sequence[Fact] = ()
    summaries: Sequence[str] = ()
    """Compressed stretches of the story, oldest first (step 6)."""
    history: Sequence[Message] = ()
    """The visible transcript, in order."""
    memories: Sequence[Recalled] = ()
    """Recalled turns, most relevant first (step 6)."""
    trackers: str | None = None
    """The meters, rendered (step 7)."""
    instruction: str | None = None
    """This turn only: a direction, a question, a reroll note."""


@dataclass(frozen=True)
class Built:
    """The messages for one call."""

    messages: list[ChatMessage]


def build(layers: Layers) -> Built:
    """Assembles the prompt, least volatile first; a layer with nothing in it is left out.

    The instruction goes as `user` when the transcript ends on a reply and as `system` when it
    ends on the reader's own turn — a model given two user turns in a row tends to answer the
    second and forget the first.
    """
    messages = [ChatMessage("system", layers.character.card)]
    if layers.persona is not None:
        messages.append(ChatMessage("system", PERSONA_FRAME + layers.persona.text))
    if layers.directives:
        messages.append(ChatMessage("system", layers.directives))
    if world := world_layer(layers.facts):
        messages.append(ChatMessage("system", world))
    if layers.summaries:
        messages.append(ChatMessage("system", "\n\n".join(layers.summaries)))
    messages += [ChatMessage(turn.role.value, turn.text) for turn in layers.history]
    if memories := memories_layer(layers.memories, layers.character, layers.persona):
        messages.append(ChatMessage("system", memories))
    if layers.trackers:
        messages.append(ChatMessage("system", layers.trackers))
    if layers.instruction:
        after_a_reply = bool(layers.history) and layers.history[-1].role is Role.ASSISTANT
        messages.append(ChatMessage("user" if after_a_reply else "system", layers.instruction))
    return Built(messages)
