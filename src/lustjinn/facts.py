"""Facts: what is true in a story right now.

The summary says what happened over a stretch; the facts say what it left true — a trait, a
possession, an injury, a commitment, a standing between people. Each fact has a validity range
in turns: `valid_from` is where it became true, `valid_to` is set when a later stretch made it
false. A world state that only accumulated would end up asserting both that she distrusts the
reader and that she trusts them, and the model would believe whichever it read last.

A fact a person stated is pinned: the extractor cannot retire it. It is not derived from the
transcript — it may be about something the story never mentioned — so nothing can prove it wrong.
"""

import json
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import background, ledger
from lustjinn.context import Fact as WorldFact
from lustjinn.memory import transcript
from lustjinn.models import Fact, Message, Persona, SpendKind, Story
from lustjinn.openrouter import ChatMessage, OpenRouter, Reply
from lustjinn.settings import Settings

log = logging.getLogger(__name__)

FACTS_TEMPERATURE = 0.2
"""Colder than the summariser: an invented fact is injected into every prompt from then on."""
FACTS_MAX_TOKENS = 4000
"""Generous: a reasoning model thinks first, and the JSON comes after."""
ID_PREFIX = 8
"""How much of a fact's id the extractor is shown, and may name to retire it."""

INSTRUCTION = (
    "You are maintaining the world state of a roleplay conversation. You are given the facts "
    "currently believed to be true, and a new stretch of transcript.\n\n"
    "Reply with JSON only, in this shape:\n"
    "{\n"
    '  "facts": [ { "subject": "...", "text": "..." } ],\n'
    '  "retired": [ "<id of a fact that is no longer true>" ]\n'
    "}\n\n"
    "Rules:\n"
    '- "facts" holds only what the new transcript establishes and the existing list does not '
    "already say. Say nothing twice.\n"
    '- "subject" is who or what it is about: a character\'s name, a place, or a pair such as '
    '"Elena and Marcus". Always a name. Never "User", "the user" or "the reader" — every '
    'person in the transcript is named there, and the story does not know who "the user" '
    "is.\n"
    '- "text" is one plain sentence, in the language of the transcript, stating something '
    "durable: a trait, a possession, an injury, a commitment, a standing between people.\n"
    "- Do not record what merely happened; that is the summary's job. Record what it left true.\n"
    '- "retired" lists the ids of existing facts the new transcript has made false. A change '
    "of heart, a wound that healed, a promise broken or kept. Be conservative: retire a fact "
    "only when the transcript actually contradicts it.\n"
    "- If there is nothing to add and nothing to retire, reply with empty arrays."
)


async def live_facts(session: AsyncSession, story_id: uuid.UUID) -> list[Fact]:
    """What the story believes right now, oldest first."""
    rows = await session.scalars(
        select(Fact)
        .where(Fact.story_id == story_id, Fact.valid_to_sequence.is_(None))
        .order_by(Fact.valid_from_sequence, Fact.created_at)
    )
    return list(rows)


def world(facts: Sequence[Fact]) -> list[WorldFact]:
    """The live facts as the context builder's world layer."""
    return [WorldFact(fact.subject, fact.text) for fact in facts]


def listed(facts: Sequence[Fact]) -> str:
    """The existing facts as the extractor sees them: a short id to retire by, then the fact."""
    if not facts:
        return "(none yet)"
    return "\n".join(f"{fact.id.hex[:ID_PREFIX]} | {fact.subject} | {fact.text}" for fact in facts)


def parse(answer: str) -> tuple[list[tuple[str, str]], list[str]]:
    """The facts and the retired ids in the model's answer, read generously: the JSON is taken
    from the first `{` to the last `}`, so a code fence or a sentence around it does no harm.
    Anything that is not the agreed shape is skipped rather than guessed at."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the answer")
    document = json.loads(answer[start : end + 1])
    if not isinstance(document, dict):
        raise ValueError("the answer is not a JSON object")
    found: list[tuple[str, str]] = []
    for entry in document.get("facts") or []:  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if not isinstance(entry, dict):
            continue
        subject = entry.get("subject")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        text = entry.get("text")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(subject, str) and isinstance(text, str) and subject.strip() and text.strip():
            found.append((subject.strip()[:200], text.strip()))
    retired = [
        item.strip()
        for item in document.get("retired") or []  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if isinstance(item, str) and item.strip()
    ]
    return found, retired


def retire(facts: Sequence[Fact], prefix: str, at_sequence: int) -> Fact | None:
    """Retires the one live, unpinned fact whose id starts with `prefix`. Nothing happens when
    the prefix matches no fact, more than one, or only a pinned one."""
    matches = [
        fact
        for fact in facts
        if fact.valid_to_sequence is None and fact.id.hex.startswith(prefix.lower())
    ]
    if len(matches) != 1 or matches[0].pinned:
        return None
    matches[0].valid_to_sequence = at_sequence
    return matches[0]


def add(
    story: Story, subject: str, text: str, at_sequence: int, *, model: str | None = None
) -> Fact:
    """A fact that became true at `at_sequence`. Without a model it was stated by a person,
    and it is pinned."""
    return Fact(
        story_id=story.id,
        subject=subject,
        text=text,
        valid_from_sequence=at_sequence,
        model=model,
        pinned=model is None,
    )


async def extract(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    persona: Persona | None,
    stretch: Sequence[Message],
) -> tuple[int, int]:
    """Reads a just-summarised stretch for what it left true. Returns (added, retired).

    Billed before the answer is judged, like the summary: an unparseable answer was still a
    call. A failure is the caller's to log — the summary stands either way.
    """
    existing = await live_facts(session, story.id)
    messages = [
        ChatMessage("system", INSTRUCTION),
        ChatMessage(
            "user",
            f"Existing facts:\n{listed(existing)}\n\nNew transcript:\n"
            + transcript(stretch, story, persona),
        ),
    ]

    async def call() -> Reply:
        return await openrouter.complete(
            messages,
            model=settings.background_model or settings.model,
            temperature=FACTS_TEMPERATURE,
            max_tokens=FACTS_MAX_TOKENS,
        )

    reply = await background.once_more_if_worth_it(call)
    session.add(ledger.row(story.id, SpendKind.FACTS, reply))
    try:
        found, retired_ids = parse(reply.text)
    except (ValueError, json.JSONDecodeError) as error:
        log.warning("fact extraction unreadable, nothing recorded: %s", error)
        await session.commit()
        return 0, 0

    first, last = stretch[0].sequence, stretch[-1].sequence
    for subject, text in found:
        session.add(add(story, subject, text, first, model=reply.model))
    retired = sum(1 for prefix in retired_ids if retire(existing, prefix, last) is not None)
    await session.commit()
    return len(found), retired
