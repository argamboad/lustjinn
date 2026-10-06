"""The memory: what lets a story outlive its budget.

Three mechanisms, each answering a different question — summaries (what happened), retrieval
(what was said) and facts (what is true now) — and one entry point, `compose`, which runs
whichever of them the story needs and then builds the prompt. A story that fits its budget costs
no extra call: nothing here fires until the transcript no longer fits.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import background, ledger, tokens
from lustjinn.context import Built, Layers, Recalled, build, reader_name
from lustjinn.models import (
    EMBEDDING_DIMENSIONS,
    Embedding,
    Message,
    Persona,
    Role,
    SpendKind,
    Story,
    Summary,
)
from lustjinn.openrouter import ChatMessage, ModelError, OpenRouter, Reply
from lustjinn.settings import Settings

log = logging.getLogger(__name__)

# How a stretch is compressed. Each figure was measured on real stories (KICKOFF, The memory).
WORTH_A_CALL = 10
"""Fewer turns than this are not worth a call: compressing only the overflow ran every turn on
two messages."""
ALWAYS_WHOLE = 6
"""The newest turns are never compressed: the scene in progress stays verbatim."""
AT_MOST_PER_SUMMARY = 40
"""One call over 99 messages came back as `##`."""
LEAST_COMPRESSION = 60
"""A summary shorter than one sixtieth of what it replaces cannot have kept it: refused."""
LEAST_SUMMARY_TOKENS = 20
ROOM_FOR_THE_REPLY = 200
"""Slack on top of the reply ceiling when deciding what fits."""

SUMMARY_TEMPERATURE = 0.3
"""A creative summariser invents history the character then believes."""
SUMMARY_MAX_TOKENS = 1200

SUMMARY_INSTRUCTION = (
    "You are compressing part of a roleplay transcript so it can be carried forward once the "
    "original turns no longer fit in the context.\n\n"
    "Write a factual account, in the same language as the transcript, covering:\n"
    "- what happened, in order\n"
    "- facts established about the characters, places and relationships\n"
    "- what changed between the participants\n"
    "- anything promised, threatened, agreed or left unresolved\n"
    "- where and how the scene was left\n\n"
    "Do not write in character, do not add events, and do not editorialise. Prefer specifics "
    "over impressions: names, places and commitments matter more than mood. Be brief."
)


def transcript(turns: Sequence[Message], story: Story, persona: Persona | None) -> str:
    """A stretch of the story as a model reads it when it is not playing it: `Name: text`,
    the reader named by their persona."""
    who = {"assistant": story.character.name, "user": reader_name(persona), "system": "Note"}
    return "\n\n".join(f"{who[turn.role.value]}: {turn.text}" for turn in turns)


async def summaries_of(session: AsyncSession, story_id: uuid.UUID) -> list[Summary]:
    rows = await session.scalars(
        select(Summary).where(Summary.story_id == story_id).order_by(Summary.from_sequence)
    )
    return list(rows)


def overflowing(recent: Sequence[Message], allowance: int) -> int:
    """How many of the oldest recent turns do not fit once the newest have taken their room."""
    used = 0
    kept = 0
    for turn in reversed(recent):
        cost = tokens.for_message(turn.text)
        if used + cost > allowance:
            break
        used += cost
        kept += 1
    return len(recent) - kept


def batch_to_compress(recent: Sequence[Message], allowance: int) -> list[Message]:
    """The oldest turns to compress now, or nothing.

    Nothing unless something no longer fits. Then at least `WORTH_A_CALL` turns if there are that
    many to spare after `ALWAYS_WHOLE`, at most `AT_MOST_PER_SUMMARY` — and never fewer than the
    overflow itself, which is why the newest six are a limit on widening the batch, not a
    guarantee: a backlog can reach past them.
    """
    overflow = overflowing(recent, allowance)
    if overflow <= 0:
        return []
    size = max(overflow, min(WORTH_A_CALL, len(recent) - ALWAYS_WHOLE))
    return list(recent[: min(size, AT_MOST_PER_SUMMARY)])


def credible(summary: str, source: Sequence[Message]) -> bool:
    """A summary short enough to have forgotten most of what it replaces is not a summary."""
    produced = tokens.count(summary)
    source_tokens = sum(tokens.count(turn.text) for turn in source)
    return produced >= max(LEAST_SUMMARY_TOKENS, source_tokens // LEAST_COMPRESSION)


async def summarise(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    persona: Persona | None,
    batch: Sequence[Message],
) -> Summary | None:
    """Compresses `batch` into one summary row. None when the model's answer was refused.

    The ledger row is written before the answer is judged: a refused summary was still billed.
    """
    messages = [
        ChatMessage("system", SUMMARY_INSTRUCTION),
        ChatMessage("user", transcript(batch, story, persona)),
    ]

    async def call() -> Reply:
        # Never a reasoning flag here: the field is for replies, and a model that cannot switch
        # it off refuses the whole call.
        return await openrouter.complete(
            messages,
            model=settings.background_model or settings.model,
            temperature=SUMMARY_TEMPERATURE,
            max_tokens=SUMMARY_MAX_TOKENS,
        )

    reply = await background.once_more_if_worth_it(call)
    session.add(ledger.row(story.id, SpendKind.SUMMARY, reply))
    text = reply.text.strip()
    if not credible(text, batch):
        log.warning("summary refused: %d tokens for %d turns", tokens.count(text), len(batch))
        await session.commit()
        return None
    summary = Summary(
        story_id=story.id,
        from_sequence=batch[0].sequence,
        to_sequence=batch[-1].sequence,
        text=text,
        model=reply.model,
        message_count=len(batch),
    )
    session.add(summary)
    await session.commit()
    return summary


BACKFILL_AT_MOST = 128
"""Turns embedded in one call when a story's compressed turns have never been embedded (a long
story meeting retrieval for the first time): the rest follow on later turns."""


def retrieval_on(settings: Settings) -> bool:
    return bool(settings.embedding_model) and settings.recall_count > 0


async def backfill(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    covered: int,
) -> int:
    """Embeds the live, summarised turns that have no vector yet — the oldest first, at most
    `BACKFILL_AT_MOST` per call. Returns how many were embedded."""
    assert settings.embedding_model is not None
    missing = list(
        await session.scalars(
            select(Message)
            .outerjoin(Embedding, Embedding.message_id == Message.id)
            .where(
                Message.story_id == story.id,
                Message.sequence <= covered,
                Message.deleted_at.is_(None),
                Embedding.message_id.is_(None),
            )
            .order_by(Message.sequence)
            .limit(BACKFILL_AT_MOST)
        )
    )
    if not missing:
        return 0
    vectors = await openrouter.embed([m.text for m in missing], model=settings.embedding_model)
    for message, vector in zip(missing, vectors, strict=True):
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ModelError(
                f"The embedding model returned {len(vector)} dimensions; the store holds "
                f"{EMBEDDING_DIMENSIONS}.",
                200,
            )
        session.add(
            Embedding(
                message_id=message.id,
                story_id=story.id,
                vector=vector,
                model=settings.embedding_model,
            )
        )
    await session.commit()
    return len(missing)


async def recall(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    covered: int,
    query: str,
) -> list[Recalled]:
    """The summarised turns nearest to `query`, most relevant first, above the threshold, at
    most `recall_count`. The builder caps them by budget share and puts them in story order."""
    assert settings.embedding_model is not None
    [wanted] = await openrouter.embed([query], model=settings.embedding_model)
    distance = Embedding.vector.cosine_distance(wanted).label("distance")
    rows = await session.execute(
        select(Message.sequence, Message.role, Message.text, distance)
        .join(Embedding, Embedding.message_id == Message.id)
        .where(
            Message.story_id == story.id,
            Message.sequence <= covered,
            Message.deleted_at.is_(None),
        )
        .order_by(distance)
        .limit(settings.recall_count)
    )
    found: list[Recalled] = []
    for sequence, role, text, how_far in rows:
        if 1 - float(how_far) >= settings.recall_threshold:
            found.append(Recalled(sequence, Role(role), text))
    return found


async def memories_for(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    covered: int,
    recent: Sequence[Message],
) -> list[Recalled]:
    """Retrieval, when there is anything to retrieve from and anything to ask with. Any failure
    — the embedding host down, a wrong dimension — costs the reader nothing but the memories."""
    if covered <= 0 or not retrieval_on(settings):
        return []
    query = next((turn.text for turn in reversed(recent) if turn.role is Role.USER), None)
    if query is None:
        return []
    try:
        await backfill(session, openrouter, settings, story, covered)
        return await recall(session, openrouter, settings, story, covered, query)
    except ModelError as error:
        log.warning("retrieval skipped: %s", error)
        return []


def _recall_estimate(settings: Settings, covered: int, recent: Sequence[Message]) -> int:
    """Room to keep for the memories retrieval will add after the batch is decided: as many
    turns as may be recalled, each about the size of a recent turn, within the recall share."""
    if covered <= 0 or not retrieval_on(settings) or not recent:
        return 0
    mean = sum(tokens.for_message(turn.text) for turn in recent) // len(recent)
    cap = settings.context_budget * settings.recall_percent // 100
    return min(settings.recall_count * mean, cap)


def _reserve(layers: Layers, settings: Settings, covered: int, recent: Sequence[Message]) -> int:
    """What the prompt costs before any history: the fixed layers, the reply, some slack, and
    the room the memories will take."""
    fixed = build(replace(layers, history=()), budget=None).estimated_tokens
    recalled = _recall_estimate(settings, covered, recent)
    return fixed + recalled + settings.max_tokens + ROOM_FOR_THE_REPLY


@dataclass(frozen=True)
class Composed(Built):
    """A built prompt that also says what the memory did to produce it."""

    summarised: Summary | None = None
    compression_failed: bool = False


async def compose(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    persona: Persona | None,
    history: Sequence[Message],
    *,
    instruction: str | None = None,
) -> Composed:
    """The prompt for the next call, after the memory has done what the story needs.

    The turns a summary already covers are not sent; the summary is. When the rest no longer
    fits, the oldest of them are compressed first — one summary per call — and the prompt is
    built again from what remains. If the summariser fails, the turns go whole and the budget is
    set aside: over budget rather than discard.
    """
    summaries = await summaries_of(session, story.id)
    covered = summaries[-1].to_sequence if summaries else 0
    recent = [turn for turn in history if turn.sequence > covered]

    def layers(turns: Sequence[Message], memories: Sequence[Recalled] = ()) -> Layers:
        return Layers(
            character=story.character,
            persona=persona,
            summaries=[s.text for s in summaries],
            history=turns,
            memories=memories,
            instruction=instruction,
        )

    summarised: Summary | None = None
    failed = False
    reserve = _reserve(layers(()), settings, covered, recent)
    allowance = max(0, settings.context_budget - reserve)
    batch = batch_to_compress(recent, allowance)
    if batch:
        try:
            summarised = await summarise(session, openrouter, settings, story, persona, batch)
        except ModelError as error:
            log.warning("summariser failed, sending the turns whole: %s", error)
            failed = True
        if summarised is not None:
            summaries.append(summarised)
            covered = summarised.to_sequence
            recent = [turn for turn in recent if turn.sequence > covered]
        else:
            failed = True

    recalled = await memories_for(session, openrouter, settings, story, covered, recent)
    built = build(
        layers(recent, recalled),
        budget=None if failed else settings.context_budget,
        recall_percent=settings.recall_percent,
    )
    return Composed(
        built.messages, built.spent, built.budget, summarised=summarised, compression_failed=failed
    )
