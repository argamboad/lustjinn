"""Cost reports from the ledger: what a story cost, what a month cost, and what bought nothing.

Every billed call left one row (`ledger`), and the reports are sums over those rows, read at
report time — so a reply rerolled away after it was billed counts as *discarded* from the
moment it is hidden. Discarded spend is the one line that bought nothing; the cached share is
how you see whether the layer order is working. A call with no price is reported as unpriced,
never as zero. Embeddings are not in the ledger and are not counted, and the report says so.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.db import get_session
from lustjinn.models import Message, Spend, SpendKind, Story
from lustjinn.stories import visible_story

router = APIRouter(tags=["spend"])
Session = Annotated[AsyncSession, Depends(get_session)]

PURGED = "(purged)"
"""The name a story's rows report under once the story itself has been erased."""
NOTE = "Embeddings are not in the ledger and are not counted."


class ByKind(BaseModel):
    kind: SpendKind
    calls: int
    cost: Decimal
    unpriced: int


class ByProvider(BaseModel):
    provider: str
    calls: int
    cost: Decimal
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    cached_share: float | None
    """Cached prompt tokens over prompt tokens: what the layer order saved."""
    completion_per_call: int


class StorySpend(BaseModel):
    story_id: uuid.UUID
    name: str
    calls: int
    cost: Decimal
    """Of the priced calls. Unpriced ones are counted apart, never as zero."""
    discarded_calls: int
    discarded_cost: Decimal
    """Spent on replies since rerolled or cut away: the one line that bought nothing."""
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cached_share: float | None
    unpriced: int
    by_kind: list[ByKind]
    first_at: datetime | None
    last_at: datetime | None


class Report(BaseModel):
    from_at: datetime | None
    to_at: datetime | None
    calls: int
    cost: Decimal
    discarded_calls: int
    discarded_cost: Decimal
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cached_share: float | None
    unpriced: int
    by_kind: list[ByKind]
    by_story: list[StorySpend]
    """The dearest first, then by name."""
    by_provider: list[ByProvider]
    note: str = NOTE


@dataclass
class _Tally:
    calls: int = 0
    cost: Decimal = Decimal(0)
    unpriced: int = 0
    discarded_calls: int = 0
    discarded_cost: Decimal = Decimal(0)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    by_kind: dict[SpendKind, _Tally] = field(default_factory=lambda: {})

    def add(self, row: Spend, discarded: bool) -> None:
        self.calls += 1
        if row.cost is None:
            self.unpriced += 1
        else:
            self.cost += row.cost
        if discarded:
            self.discarded_calls += 1
            self.discarded_cost += row.cost or 0
        self.prompt_tokens += row.prompt_tokens or 0
        self.completion_tokens += row.completion_tokens or 0
        self.cached_tokens += row.cached_tokens or 0
        self.first_at = row.at if self.first_at is None else min(self.first_at, row.at)
        self.last_at = row.at if self.last_at is None else max(self.last_at, row.at)

    @property
    def cached_share(self) -> float | None:
        return self.cached_tokens / self.prompt_tokens if self.prompt_tokens else None

    def kinds(self) -> list[ByKind]:
        return [
            ByKind(kind=kind, calls=t.calls, cost=t.cost, unpriced=t.unpriced)
            for kind, t in sorted(self.by_kind.items(), key=lambda item: item[0].value)
        ]


def _rows_query(
    from_at: datetime | None, to_at: datetime | None, story_id: uuid.UUID | None = None
):
    query = (
        select(Spend, Message.deleted_at, Story.name)
        .outerjoin(Message, Spend.message_id == Message.id)
        .outerjoin(Story, Spend.story_id == Story.id)
    )
    if from_at is not None:
        query = query.where(Spend.at >= from_at)
    if to_at is not None:
        query = query.where(Spend.at < to_at)
    if story_id is not None:
        query = query.where(Spend.story_id == story_id)
    return query


def _story_out(story_id: uuid.UUID, name: str | None, tally: _Tally) -> StorySpend:
    return StorySpend(
        story_id=story_id,
        name=name or PURGED,
        calls=tally.calls,
        cost=tally.cost,
        discarded_calls=tally.discarded_calls,
        discarded_cost=tally.discarded_cost,
        prompt_tokens=tally.prompt_tokens,
        completion_tokens=tally.completion_tokens,
        cached_tokens=tally.cached_tokens,
        cached_share=tally.cached_share,
        unpriced=tally.unpriced,
        by_kind=tally.kinds(),
        first_at=tally.first_at,
        last_at=tally.last_at,
    )


async def report(
    session: AsyncSession, from_at: datetime | None = None, to_at: datetime | None = None
) -> Report:
    """Every ledger row in `[from_at, to_at)`, summed by kind, by story and by provider."""
    whole = _Tally()
    stories: dict[uuid.UUID, tuple[str | None, _Tally]] = {}
    providers: dict[str, _Tally] = defaultdict(_Tally)
    for row, hidden_at, story_name in await session.execute(_rows_query(from_at, to_at)):
        discarded = hidden_at is not None
        for tally in (
            whole,
            whole.by_kind.setdefault(row.kind, _Tally()),
            stories.setdefault(row.story_id, (story_name, _Tally()))[1],
            stories[row.story_id][1].by_kind.setdefault(row.kind, _Tally()),
            providers[row.provider or "(unknown)"],
        ):
            tally.add(row, discarded)
    by_story = sorted(
        (_story_out(story_id, name, tally) for story_id, (name, tally) in stories.items()),
        key=lambda s: (-s.cost, s.name.lower()),
    )
    by_provider = [
        ByProvider(
            provider=name,
            calls=t.calls,
            cost=t.cost,
            prompt_tokens=t.prompt_tokens,
            cached_tokens=t.cached_tokens,
            completion_tokens=t.completion_tokens,
            cached_share=t.cached_share,
            completion_per_call=t.completion_tokens // t.calls if t.calls else 0,
        )
        for name, t in sorted(providers.items(), key=lambda item: (-item[1].cost, item[0]))
    ]
    return Report(
        from_at=from_at,
        to_at=to_at,
        calls=whole.calls,
        cost=whole.cost,
        discarded_calls=whole.discarded_calls,
        discarded_cost=whole.discarded_cost,
        prompt_tokens=whole.prompt_tokens,
        completion_tokens=whole.completion_tokens,
        cached_tokens=whole.cached_tokens,
        cached_share=whole.cached_share,
        unpriced=whole.unpriced,
        by_kind=whole.kinds(),
        by_story=by_story,
        by_provider=by_provider,
    )


async def story_report(session: AsyncSession, story: Story) -> StorySpend:
    """One story's running total, for the conversation header."""
    tally = _Tally()
    for row, hidden_at, _name in await session.execute(_rows_query(None, None, story.id)):
        tally.add(row, hidden_at is not None)
        tally.by_kind.setdefault(row.kind, _Tally()).add(row, hidden_at is not None)
    return _story_out(story.id, story.name, tally)


@router.get("/spend")
async def read_report(
    session: Session, from_at: datetime | None = None, to_at: datetime | None = None
) -> Report:
    """What everything cost in a window — `[from_at, to_at)`, both optional — by kind, by story
    (a purged story under "(purged)") and by provider."""
    return await report(session, from_at, to_at)


@router.get("/stories/{story_id}/spend")
async def read_story_report(story_id: uuid.UUID, session: Session) -> StorySpend:
    """What this story has cost so far, discarded replies and unpriced calls told apart."""
    story = await visible_story(session, story_id)
    return await story_report(session, story)
