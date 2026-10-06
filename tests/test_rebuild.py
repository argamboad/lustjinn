"""Rebuilding a story's memory: the same batches and rules as playing it, from the transcript."""

from collections.abc import Callable
from itertools import pairwise

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import facts
from lustjinn.models import Fact, SpendKind, Story, Summary
from lustjinn.settings import Settings
from scripts.seed_dummy import Dummy
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_summaries import a_budget_that_holds, a_long_story
from tests.test_turns import ledger


async def summaries_of(session: AsyncSession, story: Story) -> list[Summary]:
    rows = await session.scalars(
        select(Summary)
        .where(Summary.story_id == story.id)
        .order_by(Summary.from_sequence)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def facts_of(session: AsyncSession, story: Story) -> list[Fact]:
    rows = await session.scalars(
        select(Fact).where(Fact.story_id == story.id).execution_options(populate_existing=True)
    )
    return list(rows)


async def a_story_with_an_old_memory(
    session: AsyncSession,
    client: httpx2.AsyncClient,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> Story:
    """A long story played one turn under a tight budget, so it has a summary, extracted facts,
    a pinned fact and ledger rows made the ordinary way."""
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    session.add(facts.add(story, "Rowan Hale", "is allergic to shellfish.", 1))  # pinned
    await session.commit()
    model.summarises("Old stretch.").extracts([("Isaure", "noticed the satchel.")]).says("Hm.")
    await send(client, story.id, "I come in.")
    return story


async def rebuild(client: httpx2.AsyncClient, story_id: object, **params: str):
    return await client.post(f"/stories/{story_id}/memory/rebuild", params=params)


async def test_a_dry_run_says_what_it_would_replace_and_changes_nothing(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    story = await a_story_with_an_old_memory(session, client, model, tune, dummy)
    before = len(model.calls)

    response = await rebuild(client, story.id, dry_run="true")

    assert response.status_code == 200
    assert response.json() == {
        "dry_run": True,
        "summaries_removed": 1,
        "facts_removed": 1,
        "pinned_kept": 1,
        "summaries_written": 0,
        "facts_extracted": 0,
        "messages_covered": 0,
    }
    assert [s.text.startswith("Old stretch.") for s in await summaries_of(session, story)] == [True]
    assert len(model.calls) == before


async def test_a_rebuild_makes_the_memory_again_and_keeps_pinned_facts_and_the_ledger(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    story = await a_story_with_an_old_memory(session, client, model, tune, dummy)
    old_rows = await ledger(session, story)
    embeddings_before = len(model.embedding_calls)
    for i in range(4):  # more than a rebuild needs; what is left unused is harmless
        model.summarises(f"New stretch {i}.").extracts([("Pell", f"fact {i}.")])

    response = await rebuild(client, story.id)

    assert response.status_code == 200
    report = response.json()
    assert (report["summaries_removed"], report["facts_removed"], report["pinned_kept"]) == (
        1,
        1,
        1,
    )
    assert report["dry_run"] is False
    summaries = await summaries_of(session, story)
    assert report["summaries_written"] == len(summaries) >= 1
    assert all(s.text.startswith("New stretch") for s in summaries)
    # The same batches as playing: contiguous from the opening, each the next stretch.
    assert summaries[0].from_sequence == 1
    assert all(b.from_sequence == a.to_sequence + 1 for a, b in pairwise(summaries))
    assert (
        report["messages_covered"]
        == sum(s.message_count for s in summaries)
        == summaries[-1].to_sequence
    )
    kept = await facts_of(session, story)
    assert {f.text for f in kept if f.pinned} == {"is allergic to shellfish."}
    assert not any(f.text == "noticed the satchel." for f in kept)
    assert report["facts_extracted"] == len([f for f in kept if not f.pinned]) == len(summaries)
    rows = await ledger(session, story)
    assert {r.id for r in old_rows} <= {r.id for r in rows}  # the old calls stay
    new_kinds = sorted(r.kind for r in rows if r.id not in {o.id for o in old_rows})
    assert new_kinds == sorted([SpendKind.SUMMARY, SpendKind.FACTS] * len(summaries))
    assert len(model.embedding_calls) == embeddings_before  # nothing was recalled for


async def test_a_story_that_fits_rebuilds_to_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_long_story(session, 4)

    report = (await rebuild(client, story.id)).json()

    assert report["summaries_written"] == 0
    assert report["messages_covered"] == 0
    assert model.calls == []


async def test_a_summariser_that_refuses_ends_the_rebuild_with_what_it_managed(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    story = await a_story_with_an_old_memory(session, client, model, tune, dummy)
    model.summarises("First new.").extracts().says("##")  # the second summary is refused

    report = (await rebuild(client, story.id)).json()

    assert report["summaries_written"] == 1
    kinds = sorted(r.kind for r in await ledger(session, story))
    assert kinds.count(SpendKind.SUMMARY) == 3  # the old one, the new one, the refused one


async def test_a_missing_story_is_a_404(client: httpx2.AsyncClient) -> None:
    missing = "01a10d31-0000-7000-8000-000000000000"

    assert (await rebuild(client, missing)).status_code == 404
