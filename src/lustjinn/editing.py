"""Editing a story's shape: taking it two ways from a turn, and cutting it back to one.

Messages are append-only, so neither of these rewrites a row. A branch copies; a cut hides. What
is derived from the turns — summaries, facts, embeddings — follows rules written down here,
because the memory of turns a story no longer has would tell the model about a scene that never
happened in this version of it.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.deps import Session
from lustjinn.models import (
    Aside,
    DialValue,
    Embedding,
    Fact,
    Message,
    Story,
    Summary,
    Tracker,
    new_id,
)
from lustjinn.stories import StoryWithMessages, read_story, visible_story

router = APIRouter(prefix="/stories/{story_id}", tags=["editing"])
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BranchFrom(BaseModel):
    message_id: uuid.UUID
    """The last turn the branch keeps."""
    name: Name | None = None
    """The branch's name; the source's with a number when left out: "X (2)", then "X (3)"."""


async def _point(session: AsyncSession, story_id: uuid.UUID, message_id: uuid.UUID) -> Message:
    """A visible message of this story, or a 404."""
    message = await session.scalar(
        select(Message).where(
            Message.id == message_id, Message.story_id == story_id, Message.deleted_at.is_(None)
        )
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That message is not in this story.")
    return message


async def next_name(session: AsyncSession, source: str) -> str:
    """`source (2)`, or the next number a visible story of that name is not already using."""
    taken = set(
        await session.scalars(
            select(Story.name).where(Story.deleted_at.is_(None), Story.name.like(f"{source} (%)"))
        )
    )
    n = 2
    while f"{source} ({n})" in taken:
        n += 1
    return f"{source} ({n})"


async def branch(session: AsyncSession, source: Story, through: Message, name: str) -> Story:
    """Copies the story up to `through`, inclusive, with the memory those turns built.

    - Live messages up to the point keep their sequence numbers; hidden ones, request hashes
      do not come. Their embeddings are carried, not recomputed: the text is
      identical, so the vector is too.
    - Only summaries wholly inside the branch: one that straddles the point describes turns
      the copy does not have.
    - Facts true at the point: one retired after it was retired by turns this copy lacks, so
      here it never stopped being true.
    - Meters at the value they hold now, the one thing that cannot be rewound; dial choices as
      they stand, since a choice is configuration, not something the story did.
    - Questions asked up to the point. Never spend: the branch starts at zero.
    """
    point = through.sequence
    copy = Story(
        id=new_id(),
        name=name,
        character_id=source.character_id,
        persona_id=source.persona_id,
    )
    session.add(copy)

    originals = list(
        await session.scalars(
            select(Message)
            .where(
                Message.story_id == source.id,
                Message.deleted_at.is_(None),
                Message.sequence <= point,
            )
            .order_by(Message.sequence)
        )
    )
    copied: dict[uuid.UUID, Message] = {}
    for original in originals:
        twin = Message(
            id=new_id(),
            story_id=copy.id,
            sequence=original.sequence,
            role=original.role,
            text=original.text,
            model=original.model,
            provider=original.provider,
            prompt_tokens=original.prompt_tokens,
            completion_tokens=original.completion_tokens,
            estimated_prompt_tokens=original.estimated_prompt_tokens,
            context_audit=original.context_audit,
            sent_at=original.sent_at,
        )
        copied[original.id] = twin
        session.add(twin)

    vectors = await session.scalars(select(Embedding).where(Embedding.message_id.in_(list(copied))))
    for vector in vectors:
        session.add(
            Embedding(
                message_id=copied[vector.message_id].id,
                story_id=copy.id,
                vector=vector.vector,
                model=vector.model,
            )
        )

    summaries = await session.scalars(
        select(Summary).where(Summary.story_id == source.id, Summary.to_sequence <= point)
    )
    for summary in summaries:
        session.add(
            Summary(
                story_id=copy.id,
                from_sequence=summary.from_sequence,
                to_sequence=summary.to_sequence,
                text=summary.text,
                model=summary.model,
                message_count=summary.message_count,
                created_at=summary.created_at,
            )
        )

    facts = await session.scalars(
        select(Fact).where(Fact.story_id == source.id, Fact.valid_from_sequence <= point)
    )
    for fact in facts:
        retired_later = fact.valid_to_sequence is not None and fact.valid_to_sequence > point
        session.add(
            Fact(
                story_id=copy.id,
                subject=fact.subject,
                text=fact.text,
                valid_from_sequence=fact.valid_from_sequence,
                valid_to_sequence=None if retired_later else fact.valid_to_sequence,
                model=fact.model,
                pinned=fact.pinned,
                created_at=fact.created_at,
            )
        )

    meters = await session.scalars(select(Tracker).where(Tracker.story_id == source.id))
    for meter in meters:
        session.add(
            Tracker(
                story_id=copy.id,
                name=meter.name,
                value=meter.value,
                max=meter.max,
                delta=meter.delta,
                note=meter.note,
                means=meter.means,
                anchors=meter.anchors,
                rule=meter.rule,
                updated_at_sequence=None
                if meter.updated_at_sequence is None
                else min(meter.updated_at_sequence, point),
                created_at=meter.created_at,
            )
        )

    choices = await session.scalars(select(DialValue).where(DialValue.story_id == source.id))
    for choice in choices:
        session.add(DialValue(story_id=copy.id, key=choice.key, value=choice.value))

    asides = await session.scalars(
        select(Aside).where(Aside.story_id == source.id, Aside.sequence <= point)
    )
    for aside in asides:
        session.add(
            Aside(
                story_id=copy.id,
                sequence=aside.sequence,
                question=aside.question,
                answer=aside.answer,
                asked_at=aside.asked_at,
                model=aside.model,
                provider=aside.provider,
                prompt_tokens=aside.prompt_tokens,
                completion_tokens=aside.completion_tokens,
                estimated_prompt_tokens=aside.estimated_prompt_tokens,
                context_audit=aside.context_audit,
            )
        )

    await session.commit()
    return copy


@router.post("/branch", status_code=status.HTTP_201_CREATED)
async def branch_story(
    story_id: uuid.UUID, body: BranchFrom, session: Session
) -> StoryWithMessages:
    """Copies the story up to a turn, under a new name, with the memory those turns built. The
    original is untouched, and the copy starts with nothing on its bill."""
    source = await visible_story(session, story_id)
    through = await _point(session, story_id, body.message_id)
    name = body.name or await next_name(session, source.name)
    copy = await branch(session, source, through, name)
    return await read_story(copy.id, session)


class Cut(BaseModel):
    """What a cut left behind, so a client can say so."""

    story: StoryWithMessages
    hidden: int
    summaries_removed: int
    facts_removed: int
    facts_reopened: int


async def cut(session: AsyncSession, story: Story, start: Message) -> Cut:
    """Hides `start` and every visible turn after it, and takes the memory of those turns with
    it.

    Hidden, never deleted: the rows stay, as the trigger insists. The memory is derived, and
    memory of turns the story no longer has would tell the model about a scene that never
    happened in this version — so a summary that reaches the cut goes, a fact extracted from
    it goes (a pinned one stays: a person said it), and a fact those turns had retired is true
    again. Meters cannot be rewound and keep their value; questions keep their answers.
    """
    now = datetime.now(UTC)
    doomed = list(
        await session.scalars(
            select(Message).where(
                Message.story_id == story.id,
                Message.sequence >= start.sequence,
                Message.deleted_at.is_(None),
            )
        )
    )
    for message in doomed:
        message.deleted_at = now
        message.request_hash = None  # sending the same words again is a new turn

    summaries = list(
        await session.scalars(
            select(Summary).where(
                Summary.story_id == story.id, Summary.to_sequence >= start.sequence
            )
        )
    )
    for summary in summaries:
        await session.delete(summary)

    facts = list(await session.scalars(select(Fact).where(Fact.story_id == story.id)))
    removed = 0
    reopened = 0
    for fact in facts:
        if fact.valid_from_sequence >= start.sequence and not fact.pinned:
            await session.delete(fact)
            removed += 1
        elif fact.valid_to_sequence is not None and fact.valid_to_sequence >= start.sequence:
            fact.valid_to_sequence = None
            reopened += 1

    await session.commit()
    return Cut(
        story=await read_story(story.id, session),
        hidden=len(doomed),
        summaries_removed=len(summaries),
        facts_removed=removed,
        facts_reopened=reopened,
    )


@router.delete("/messages/{message_id}")
async def delete_from(story_id: uuid.UUID, message_id: uuid.UUID, session: Session) -> Cut:
    """Cuts the story back to just before this message: it and everything after it are hidden,
    with the memory those turns built. The rows stay in the table."""
    story = await visible_story(session, story_id)
    start = await _point(session, story_id, message_id)
    return await cut(session, story, start)
