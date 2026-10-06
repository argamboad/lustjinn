"""Rebuilding a story's memory from its transcript.

The memory is derived and the transcript is never deleted, so memory made badly by an earlier
version can be made again. A rebuild throws away the summaries and the extracted facts and
replays the ordinary compose path over the transcript — the one that compresses while playing
— until it finds nothing left to do. A rebuild that used rules of its own would produce a memory
the application never would. Pinned facts are kept: a person stated them. The old calls stay in
the ledger and the rebuild's calls are added beside them: the money was spent either way.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from lustjinn import dials, memory, story_model, trackers
from lustjinn.db import get_session
from lustjinn.library import default_persona
from lustjinn.models import Fact, Message, Story, Summary
from lustjinn.openrouter import OpenRouter, get_openrouter
from lustjinn.settings import Settings, get_settings
from lustjinn.stories import visible_story

MOST_PASSES = 200
"""Every pass either compresses a stretch or finds nothing to do, so the bound is the transcript
itself; this only stops a rebuild early if something is wrong, and then it says what it managed
rather than spinning."""


class Rebuilt(BaseModel):
    dry_run: bool
    """True: nothing was changed; the counts say what a rebuild would replace."""
    summaries_removed: int
    facts_removed: int
    pinned_kept: int
    summaries_written: int
    facts_extracted: int
    messages_covered: int
    """How many turns the new summaries cover between them."""


async def _summaries(session: AsyncSession, story_id: uuid.UUID) -> int:
    return await session.scalar(select(func.count()).where(Summary.story_id == story_id)) or 0


async def rebuild(
    session: AsyncSession,
    openrouter: OpenRouter,
    settings: Settings,
    story: Story,
    *,
    dry_run: bool,
) -> Rebuilt:
    """Replaces the story's derived memory, or with `dry_run` only says what it would replace."""
    removed_summaries = await _summaries(session, story.id)
    derived = (
        await session.scalar(
            select(func.count()).where(Fact.story_id == story.id, Fact.pinned.is_(False))
        )
        or 0
    )
    pinned = (
        await session.scalar(
            select(func.count()).where(Fact.story_id == story.id, Fact.pinned.is_(True))
        )
        or 0
    )
    if dry_run:
        return Rebuilt(
            dry_run=True,
            summaries_removed=removed_summaries,
            facts_removed=derived,
            pinned_kept=pinned,
            summaries_written=0,
            facts_extracted=0,
            messages_covered=0,
        )

    await session.execute(delete(Summary).where(Summary.story_id == story.id))
    await session.execute(delete(Fact).where(Fact.story_id == story.id, Fact.pinned.is_(False)))
    await session.commit()

    # Composed as a turn would be — the dials' layer, the meters, the fitted budget — so the
    # batches fall where playing would have put them.
    persona = story.persona if story.persona is not None else await default_persona(session)
    fitted = story_model.fitted(settings, story)
    pack = dials.shipped()
    values = await dials.values_of(session, story.id)
    directives = dials.directives(pack, values)
    ceiling = dials.sampler(pack, values).max_tokens or settings.max_tokens
    meters = trackers.render(await trackers.of(session, story.id))
    history = list(
        await session.scalars(
            select(Message)
            .where(Message.story_id == story.id, Message.deleted_at.is_(None))
            .order_by(Message.sequence)
        )
    )
    written = 0
    for _ in range(MOST_PASSES):
        before = await _summaries(session, story.id)
        await memory.compose(
            session,
            openrouter,
            fitted,
            story,
            persona,
            history,
            directives=directives,
            trackers=meters,
            reply_tokens=ceiling,
            retrieval=False,  # nothing is asked, so there is nothing to recall for
        )
        after = await _summaries(session, story.id)
        if after == before:
            break
        written = after

    extracted = (
        await session.scalar(
            select(func.count()).where(Fact.story_id == story.id, Fact.pinned.is_(False))
        )
        or 0
    )
    covered = (
        await session.scalar(
            select(func.sum(Summary.message_count)).where(Summary.story_id == story.id)
        )
        or 0
    )
    return Rebuilt(
        dry_run=False,
        summaries_removed=removed_summaries,
        facts_removed=derived,
        pinned_kept=pinned,
        summaries_written=written,
        facts_extracted=extracted,
        messages_covered=int(covered),
    )


router = APIRouter(prefix="/stories/{story_id}/memory", tags=["memory"])
Session = Annotated[AsyncSession, Depends(get_session)]
Model = Annotated[OpenRouter, Depends(get_openrouter)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]


@router.post("/rebuild")
async def rebuild_memory(
    story_id: uuid.UUID,
    session: Session,
    openrouter: Model,
    settings: CurrentSettings,
    dry_run: bool = False,
) -> Rebuilt:
    """Throws away the summaries and extracted facts and makes them again from the transcript,
    in the same batches and by the same rules as playing it. `dry_run` only says what it would
    replace. Pinned facts stay; the ledger keeps the old calls and gains the new."""
    await visible_story(session, story_id)
    story = await session.scalar(
        select(Story)
        .options(joinedload(Story.character), joinedload(Story.persona))
        .where(Story.id == story_id)
    )
    assert story is not None
    return await rebuild(session, openrouter, settings, story, dry_run=dry_run)
