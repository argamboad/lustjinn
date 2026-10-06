"""Delete a message and everything after it: the story is cut back, the rows stay."""

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.context import WORLD_FRAME
from lustjinn.models import Aside, Fact, Summary, Tracker
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_branching import a_story_with_a_memory
from tests.test_retrieval import embedded
from tests.test_turns import ledger, messages


async def cut(client: httpx2.AsyncClient, story_id: object, message_id: object):
    return await client.delete(f"/stories/{story_id}/messages/{message_id}")


async def test_the_story_ends_before_the_chosen_turn_and_the_rows_stay(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)

    response = await cut(client, story.id, turns[7].id)  # sequence 8

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["hidden"] == 3  # 8, 9, 10
    assert [m["sequence"] for m in report["story"]["messages"]] == [1, 2, 3, 4, 5, 7]
    everything = await messages(session, story, hidden=True)
    assert len(everything) == 10  # nothing deleted
    assert [m.sequence for m in everything if m.deleted_at is None] == [1, 2, 3, 4, 5, 7]
    assert all(m.request_hash is None for m in everything if m.sequence >= 8)
    read = (await client.get(f"/stories/{story.id}")).json()
    assert [m["sequence"] for m in read["messages"]] == [1, 2, 3, 4, 5, 7]


async def test_the_memory_of_the_hidden_turns_goes_with_them(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)

    report = (await cut(client, story.id, turns[7].id)).json()

    assert (report["summaries_removed"], report["facts_removed"], report["facts_reopened"]) == (
        1,
        1,
        1,
    )
    summaries = list(await session.scalars(select(Summary).where(Summary.story_id == story.id)))
    assert [(s.from_sequence, s.to_sequence) for s in summaries] == [(1, 7)]  # 8-10 reached the cut
    facts = {
        f.text: f for f in await session.scalars(select(Fact).where(Fact.story_id == story.id))
    }
    assert set(facts) == {"has room seven.", "distrusts Rowan.", "is allergic to shellfish."}
    assert facts["distrusts Rowan."].valid_to_sequence is None  # retired by a turn now gone
    assert facts["is allergic to shellfish."].pinned
    assert await embedded(session, story) == [1, 2, 3, 4, 5, 6, 7]  # vectors are kept with the rows
    [meter] = await session.scalars(select(Tracker).where(Tracker.story_id == story.id))
    assert meter.value == 55  # cannot be rewound
    asides = list(await session.scalars(select(Aside).where(Aside.story_id == story.id)))
    assert len(asides) == 2  # answers are kept
    assert len(await ledger(session, story)) == 1  # the bill does not move


async def test_a_pinned_fact_stated_after_the_cut_stays(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)
    session.add(
        Fact(story_id=story.id, subject="Pell", text="limps.", valid_from_sequence=9, pinned=True)
    )
    await session.commit()

    report = (await cut(client, story.id, turns[7].id)).json()

    assert report["facts_removed"] == 1  # the extracted one at 9, not the pinned one
    texts = {f.text for f in await session.scalars(select(Fact).where(Fact.story_id == story.id))}
    assert "limps." in texts


async def test_the_next_prompt_ends_at_the_cut(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story, turns = await a_story_with_a_memory(session)
    await cut(client, story.id, turns[7].id)
    model.says("She looks up.")

    streamed = await send(client, story.id, "I ask about the room.")

    assert streamed.done["sent"]["sequence"] == 11  # a number is never reused
    sent = [m["content"] for m in model.last["messages"]]
    assert not any("Recent" in t for t in sent)  # turns 8-10 are gone from the prompt
    assert not any(t.startswith("Later.") for t in sent)  # and so is their summary
    world = next(t for t in sent if t.startswith(WORLD_FRAME))
    assert "Isaure: distrusts Rowan." in world


async def test_cutting_from_the_newest_turn_hides_only_it(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)

    report = (await cut(client, story.id, turns[9].id)).json()

    assert report["hidden"] == 1
    assert [m["sequence"] for m in report["story"]["messages"]][-1] == 9


async def test_the_message_must_be_a_visible_turn_of_this_story(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)

    hidden = await cut(client, story.id, turns[5].id)
    missing = await cut(client, story.id, "01a10d31-0000-7000-8000-000000000000")

    assert hidden.status_code == 404
    assert missing.status_code == 404
    assert len(await messages(session, story)) == 9  # nothing moved
