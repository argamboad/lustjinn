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

from lustjinn import tokens
from lustjinn.models import Character, Message, Persona, Role
from lustjinn.openrouter import ChatMessage

PERSONA_FRAME = (
    "The user is playing the following person. Speak to them as this person, and never write "
    "their words or actions for them.\n\n"
)
DIRECTIVES_FRAME = (
    "The reader has set how this story is told. These settings outrank anything in the "
    "character's description that disagrees with them. The character stays who they are, in "
    "voice, history and manner, and acts the settings out through that: a shy character at the "
    "highest heat is shy and losing that fight, not suddenly someone else.\n\n"
)
"""Says what the dials' lines are and which side wins. Sent bare, after a card of thousands of
tokens, they read as notes: the model split the difference and the card mostly won (#142)."""
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
    """The dials, rendered (step 7); sent under `DIRECTIVES_FRAME`."""
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
class Spent:
    """What one layer cost, and what of it was left out to fit."""

    tokens: int
    dropped: int = 0


@dataclass(frozen=True)
class Built:
    """The messages for one call, and the accounting behind them."""

    messages: list[ChatMessage]
    spent: dict[str, Spent]
    """Per layer, in prompt order, only the layers that contributed something."""
    budget: int | None
    """What the history had to fit under; None when nothing was trimmed by design."""

    @property
    def estimated_tokens(self) -> int:
        return sum(layer.tokens for layer in self.spent.values())

    def describe(self) -> str:
        """One line that says what the prompt was built from, for the audit kept with each
        reply: `character 2755 · persona 412 · history 1830 (12 dropped) · total 4997/32000`."""
        parts = [
            f"{name} {layer.tokens}" + (f" ({layer.dropped} dropped)" if layer.dropped else "")
            for name, layer in self.spent.items()
        ]
        total = f"total {self.estimated_tokens}"
        if self.budget is not None:
            total += f"/{self.budget}"
        return " · ".join([*parts, total])


def _fit_memories(
    recalled: Sequence[Recalled], character: Character, persona: Persona | None, cap: int | None
) -> tuple[str | None, int]:
    """The memories layer under its cap: most relevant first, each kept if it still fits, then
    put back in story order so the model reads them as a transcript. Returns the layer and how
    many were left out."""
    kept: list[Recalled] = []
    for turn in recalled:
        attempt = memories_layer([*kept, turn], character, persona)
        if cap is not None and attempt is not None and tokens.for_message(attempt) > cap:
            continue  # this one does not fit; a shorter one further down the list still may
        kept.append(turn)
    kept.sort(key=lambda turn: turn.sequence)
    return memories_layer(kept, character, persona), len(recalled) - len(kept)


def _fit_history(history: Sequence[Message], room: int | None) -> tuple[list[Message], int]:
    """The newest turns that fit in `room`, newest first, stopping at the first that does not.

    The newest message is always kept, whatever it costs: a prompt that leaves out the words
    the reader just typed is a reply to nothing. A real story lost one that way, once.
    """
    if not history:
        return [], 0
    kept = [history[-1]]
    used = tokens.for_message(history[-1].text)
    for turn in reversed(history[:-1]):
        cost = tokens.for_message(turn.text)
        if room is not None and used + cost > room:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept, len(history) - len(kept)


ORDER = (
    "character",
    "persona",
    "directives",
    "world",
    "summaries",
    "history",
    "memories",
    "trackers",
    "instruction",
)


def build(layers: Layers, *, budget: int | None = None, recall_percent: int = 10) -> Built:
    """Assembles the prompt, least volatile first; a layer with nothing in it is left out.

    Every layer but the history is fixed: it goes in whole. The history gets what is left of the
    budget, newest turns first, and gives way oldest first when the budget binds. Recalled
    memories are capped at `recall_percent` of the budget, whatever their count: four long
    recalled turns once filled a 60,000-token prompt.

    The instruction goes as `user` when the transcript ends on a reply and as `system` when it
    ends on the reader's own turn — a model given two user turns in a row tends to answer the
    second and forget the first.
    """
    spent: dict[str, Spent] = {}

    def fixed(name: str, text: str | None, dropped: int = 0) -> ChatMessage | None:
        if not text:
            return None
        spent[name] = Spent(tokens.for_message(text), dropped)
        return ChatMessage("system", text)

    cap = None if budget is None else budget * recall_percent // 100
    memories, memories_dropped = _fit_memories(
        layers.memories, layers.character, layers.persona, cap
    )
    before = [
        fixed("character", layers.character.card),
        fixed("persona", None if layers.persona is None else PERSONA_FRAME + layers.persona.text),
        fixed("directives", layers.directives and DIRECTIVES_FRAME + layers.directives),
        fixed("world", world_layer(layers.facts)),
        fixed("summaries", "\n\n".join(layers.summaries) if layers.summaries else None),
    ]
    after = [
        fixed("memories", memories, memories_dropped),
        fixed("trackers", layers.trackers),
    ]
    instruction: ChatMessage | None = None
    if layers.instruction:
        after_a_reply = bool(layers.history) and layers.history[-1].role is Role.ASSISTANT
        instruction = ChatMessage("user" if after_a_reply else "system", layers.instruction)
        spent["instruction"] = Spent(tokens.for_message(layers.instruction))

    room = None if budget is None else max(0, budget - sum(s.tokens for s in spent.values()))
    history, history_dropped = _fit_history(layers.history, room)
    if history:
        spent["history"] = Spent(
            sum(tokens.for_message(turn.text) for turn in history), history_dropped
        )

    messages = [m for m in before if m is not None]
    messages += [ChatMessage(turn.role.value, turn.text) for turn in history]
    messages += [m for m in after if m is not None]
    if instruction is not None:
        messages.append(instruction)
    return Built(messages, {name: spent[name] for name in ORDER if name in spent}, budget)
