"""Branching: a story taken two ways from a turn, with the memory those turns built."""

import uuid
from datetime import UTC, datetime

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import facts as facts_module
from lustjinn.context import WORLD_FRAME
from lustjinn.models import (
    Aside,
    DialValue,
    Embedding,
    Fact,
    Message,
    Story,
    Summary,
    Tracker,
)
from tests.factories import a_message, a_spend
from tests.scripted_model import ScriptedModel, keyword_vector
from tests.streaming import send
from tests.test_retrieval import PLAIN, a_compressed_story, embedded
from tests.test_turns import ledger, messages


async def a_story_with_a_memory(session: AsyncSession) -> tuple[Story, list[Message]]:
    """The dummy story: opening, six turns covered by a summary (1-7), three recent turns
    (8-10), a straddling summary over 8-10, facts of every kind, embeddings over the covered
    turns, a meter, a dial, two questions, a rerolled reply hidden at 6, and a bill."""
    story = await a_compressed_story(session, [f"Turn {i}. {PLAIN}" for i in range(6)])
    turns = await messages(session, story, hidden=True)
    turns[5].deleted_at = datetime.now(UTC)  # sequence 6, rerolled away
    session.add_all(
        [
            Summary(
                story_id=story.id,
                from_sequence=8,
                to_sequence=10,
                text="Later. " * 10,
                message_count=3,
            ),
            facts_module.add(story, "Rowan Hale", "has room seven.", 2, model="m"),
            facts_module.add(story, "Isaure", "distrusts Rowan.", 3, model="m"),
            facts_module.add(story, "Rowan Hale", "is allergic to shellfish.", 4),  # pinned
            facts_module.add(story, "Isaure", "trusts Rowan.", 9, model="m"),
            Tracker(
                story_id=story.id, name="Trust", value=55, max=100, delta=5, updated_at_sequence=10
            ),
            DialValue(story_id=story.id, key="lust", value="3"),
            Aside(story_id=story.id, sequence=5, question="Who?", answer="Isaure."),
            Aside(story_id=story.id, sequence=9, question="Why?", answer="Because."),
        ]
    )
    for turn in turns[:7]:
        session.add(
            Embedding(
                message_id=turn.id, story_id=story.id, vector=keyword_vector(turn.text), model="e"
            )
        )
    await session.flush()
    retired = await session.scalar(
        select(Fact).where(Fact.story_id == story.id, Fact.text == "distrusts Rowan.")
    )
    assert retired is not None
    retired.valid_to_sequence = 9  # retired by turn 9, after the branch point
    await a_spend(session, story)
    await session.commit()
    return story, turns


async def branch(client: httpx2.AsyncClient, story_id: object, message_id: object, **more: object):
    return await client.post(
        f"/stories/{story_id}/branch", json={"message_id": str(message_id), **more}
    )


async def test_a_branch_has_exactly_the_turns_and_memory_the_rules_allow(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)
    point = turns[7]  # sequence 8, the first recent turn

    response = await branch(client, story.id, point.id)

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["name"] == "First night (2)"
    assert copy["character_id"] == str(story.character_id)
    assert copy["persona_id"] == str(story.persona_id)
    copied = await messages(session, Story(id=uuid.UUID(copy["id"])), hidden=True)
    assert [m.sequence for m in copied] == [1, 2, 3, 4, 5, 7, 8]  # 6 was hidden, and stays behind
    assert all(m.deleted_at is None and m.request_hash is None for m in copied)
    assert [m.text for m in copied] == [
        t.text for t in turns if t.sequence in (1, 2, 3, 4, 5, 7, 8)
    ]
    assert all(m.id != t.id for m, t in zip(copied, turns, strict=False))

    branch_id = uuid.UUID(copy["id"])
    summaries = list(await session.scalars(select(Summary).where(Summary.story_id == branch_id)))
    assert [(s.from_sequence, s.to_sequence) for s in summaries] == [(1, 7)]  # 8-10 straddles

    copied_facts = {
        f.text: f for f in await session.scalars(select(Fact).where(Fact.story_id == branch_id))
    }
    assert set(copied_facts) == {"has room seven.", "distrusts Rowan.", "is allergic to shellfish."}
    assert copied_facts["distrusts Rowan."].valid_to_sequence is None  # retired later: true again
    assert copied_facts["is allergic to shellfish."].pinned

    assert await embedded(session, Story(id=branch_id)) == [
        1,
        2,
        3,
        4,
        5,
        7,
    ]  # carried, not recomputed
    [meter] = await session.scalars(select(Tracker).where(Tracker.story_id == branch_id))
    assert (meter.name, meter.value, meter.updated_at_sequence) == ("Trust", 55, 8)
    [dial] = await session.scalars(select(DialValue).where(DialValue.story_id == branch_id))
    assert (dial.key, dial.value) == ("lust", "3")
    asides = list(await session.scalars(select(Aside).where(Aside.story_id == branch_id)))
    assert [a.question for a in asides] == ["Who?"]
    assert await ledger(session, Story(id=branch_id)) == []  # the branch starts at zero


async def test_the_original_is_untouched(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    story, turns = await a_story_with_a_memory(session)

    await branch(client, story.id, turns[7].id)

    assert len(await messages(session, story, hidden=True)) == 10
    assert (
        len(list(await session.scalars(select(Summary).where(Summary.story_id == story.id)))) == 2
    )
    assert len(await ledger(session, story)) == 1


async def test_a_branch_plays_on_from_its_point_with_the_memory_it_was_given(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story, turns = await a_story_with_a_memory(session)
    copy = (await branch(client, story.id, turns[7].id)).json()
    model.says("She looks up.")

    streamed = await send(client, copy["id"], "I ask about the room.")

    assert streamed.done["sent"]["sequence"] == 9  # right after the branch point
    assert streamed.done["reply"]["sequence"] == 10
    texts = [m["content"] for m in model.last["messages"]]
    assert any(t.startswith("Earlier: Rowan arrived") for t in texts)  # the copied summary
    world = next(t for t in texts if t.startswith(WORLD_FRAME))
    assert "Isaure: distrusts Rowan." in world  # true again in this version
    assert "trusts Rowan." not in world.replace("distrusts", "")
    assert len(await ledger(session, story)) == 1  # the original's bill did not move


async def test_branches_are_numbered_unless_named(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)

    second = (await branch(client, story.id, turns[3].id)).json()
    third = (await branch(client, story.id, turns[3].id)).json()
    named = (await branch(client, story.id, turns[3].id, name="  The other way  ")).json()

    assert (second["name"], third["name"], named["name"]) == (
        "First night (2)",
        "First night (3)",
        "The other way",
    )
    assert [m["sequence"] for m in named["messages"]] == [1, 2, 3, 4]


async def test_the_point_must_be_a_visible_turn_of_this_story(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story, turns = await a_story_with_a_memory(session)
    other = await a_compressed_story(session, ["Elsewhere."])
    elsewhere = await a_message(session, other, "Not here.")
    await session.commit()

    foreign = await branch(client, story.id, elsewhere.id)
    hidden = await branch(client, story.id, turns[5].id)

    assert foreign.status_code == 404
    assert hidden.status_code == 404
    assert foreign.json()["detail"] == "That message is not in this story."
    assert len(list(await session.scalars(select(Story)))) == 2  # nothing was created
