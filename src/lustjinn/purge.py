"""Erasing a story for good. Delete only hides; this is the real erasure.

A purge removes the story and every row that carries its text — messages, their embeddings,
summaries, facts, meters, questions, dial choices — and keeps the ledger. The spend rows hold no
story text, the money left the account whatever became of the story, and dropping them would
make every report for that month wrong; they report under "(purged)" from then on.

It erases only a story already deleted: two deliberate acts, not one. And it is the one path on
which the append-only trigger stands aside, by a setting local to this transaction, which the
trigger itself insists on (migration 0002).
"""

import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.deps import Session
from lustjinn.models import (
    Aside,
    DialValue,
    Embedding,
    Fact,
    Message,
    Spend,
    Story,
    Summary,
    Tracker,
)

router = APIRouter(prefix="/stories/{story_id}", tags=["editing"])


class Purged(BaseModel):
    """What was erased, and what was kept."""

    messages: int
    embeddings: int
    summaries: int
    facts: int
    trackers: int
    asides: int
    dial_values: int
    ledger_rows_kept: int
    ledger_cost_kept: Decimal


async def purge(session: AsyncSession, story: Story) -> Purged:
    """Erases the story's rows, in one transaction, with the trigger told why."""
    kept_rows, kept_cost = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Spend.cost), 0)).where(
                Spend.story_id == story.id
            )
        )
    ).one()
    # What SET LOCAL does, as a function call: on for this transaction only. The trigger
    # reads it and lets the DELETE through; it still refuses an UPDATE of a message's text.
    await session.execute(text("SELECT set_config('lustjinn.purging', 'on', true)"))
    counts: dict[str, int] = {}
    for name, table in (
        ("embeddings", Embedding),
        ("messages", Message),
        ("summaries", Summary),
        ("facts", Fact),
        ("trackers", Tracker),
        ("asides", Aside),
        ("dial_values", DialValue),
    ):
        counts[name] = (
            await session.scalar(select(func.count()).where(table.story_id == story.id)) or 0
        )
        await session.execute(delete(table).where(table.story_id == story.id))
    await session.delete(story)
    await session.commit()
    return Purged(
        **counts, ledger_rows_kept=int(kept_rows), ledger_cost_kept=Decimal(kept_cost or 0)
    )


@router.post("/purge")
async def purge_story(story_id: uuid.UUID, session: Session) -> Purged:
    """Erases a deleted story and everything that carries its text. The ledger survives: the
    story's spend reports under "(purged)" from now on. This cannot be undone."""
    story = await session.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no story with that id.")
    if story.deleted_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Delete the story first: a purge erases only stories already deleted.",
        )
    return await purge(session, story)
