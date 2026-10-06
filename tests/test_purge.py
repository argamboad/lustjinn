"""Purge: the real erasure. Nothing of the story's text stays; its spend does."""

from decimal import Decimal

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from lustjinn.spend import PURGED
from tests.test_branching import a_story_with_a_memory

TABLES = (Message, Embedding, Summary, Fact, Tracker, Aside, DialValue)


async def rows_of(session: AsyncSession, story_id: object) -> dict[str, int]:
    found: dict[str, int] = {}
    for table in TABLES:
        count = await session.scalar(select(func.count()).where(table.story_id == story_id))
        found[table.__tablename__] = count or 0
    return found


async def test_a_purged_story_leaves_no_text_in_any_table_and_its_spend_still_reports(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, _turns = await a_story_with_a_memory(session)
    before = await rows_of(session, story.id)
    assert all(before.values())
    await client.delete(f"/stories/{story.id}")

    response = await client.post(f"/stories/{story.id}/purge")

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["messages"] == 10
    assert report["embeddings"] == 7
    assert (report["summaries"], report["facts"], report["trackers"]) == (2, 4, 1)
    assert (report["asides"], report["dial_values"]) == (2, 1)
    assert report["ledger_rows_kept"] == 1
    assert Decimal(report["ledger_cost_kept"]) == Decimal("0.0002")
    assert set((await rows_of(session, story.id)).values()) == {0}
    assert await session.get(Story, story.id) is None
    [spend] = await session.scalars(select(Spend).where(Spend.story_id == story.id))
    assert spend.cost == Decimal("0.0002")
    spent = (await client.get("/spend")).json()
    assert [(s["name"], s["calls"]) for s in spent["by_story"]] == [(PURGED, 1)]


async def test_a_visible_story_cannot_be_purged(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, _turns = await a_story_with_a_memory(session)

    response = await client.post(f"/stories/{story.id}/purge")

    assert response.status_code == 409
    assert "Delete the story first" in response.json()["detail"]
    assert (await rows_of(session, story.id))["messages"] == 10


async def test_a_purged_story_is_gone_for_good(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, _turns = await a_story_with_a_memory(session)
    await client.delete(f"/stories/{story.id}")
    await client.post(f"/stories/{story.id}/purge")

    again = await client.post(f"/stories/{story.id}/purge")
    read = await client.get(f"/stories/{story.id}")

    assert again.status_code == 404
    assert read.status_code == 404


async def test_other_stories_are_untouched(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    doomed, _turns = await a_story_with_a_memory(session)
    kept, _more = await a_story_with_a_memory(session)
    await client.delete(f"/stories/{doomed.id}")

    await client.post(f"/stories/{doomed.id}/purge")

    assert (await rows_of(session, kept.id))["messages"] == 10
    assert await session.get(Story, kept.id) is not None
