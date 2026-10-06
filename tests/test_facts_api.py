"""Facts are editable: see what a story believes, add a pinned fact, retire one."""

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import facts
from lustjinn.context import WORLD_FRAME
from lustjinn.models import Fact, Role
from tests.factories import a_message
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_turns import a_played_story, messages


async def test_a_fact_is_added_pinned_listed_and_in_the_next_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await a_message(session, story, "I come in.", Role.USER)
    await session.commit()

    added = await client.post(
        f"/stories/{story.id}/facts",
        json={"subject": " Rowan Hale ", "text": " is allergic to shellfish. "},
    )
    listed = (await client.get(f"/stories/{story.id}/facts")).json()
    model.says("Hm.")
    await send(client, story.id, "I sit.")

    assert added.status_code == 201, added.text
    fact = added.json()
    assert (fact["subject"], fact["text"]) == ("Rowan Hale", "is allergic to shellfish.")
    assert fact["pinned"] is True
    assert fact["model"] is None
    assert fact["valid_from_sequence"] == 2  # where the story stood
    assert fact["valid_to_sequence"] is None
    assert listed == [fact]
    world = next(
        m["content"] for m in model.last["messages"] if m["content"].startswith(WORLD_FRAME)
    )
    assert world == WORLD_FRAME + "Rowan Hale: is allergic to shellfish."


async def test_retiring_a_fact_keeps_the_row_and_leaves_the_next_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    session.add(facts.add(story, "Isaure", "distrusts Rowan.", 1, model="m"))
    await session.commit()
    [fact] = (await client.get(f"/stories/{story.id}/facts")).json()

    retired = await client.delete(f"/stories/{story.id}/facts/{fact['id']}")
    live = (await client.get(f"/stories/{story.id}/facts")).json()
    everything = (await client.get(f"/stories/{story.id}/facts", params={"all": "true"})).json()
    model.says("Hm.")
    await send(client, story.id, "I sit.")

    assert retired.status_code == 200
    assert retired.json()["valid_to_sequence"] == 1  # the opening is the newest turn
    assert live == []
    assert [f["text"] for f in everything] == ["distrusts Rowan."]
    assert not any(m["content"].startswith(WORLD_FRAME) for m in model.last["messages"])
    [row] = await session.scalars(select(Fact).where(Fact.story_id == story.id))
    assert row.valid_to_sequence == 1


async def test_a_person_can_retire_what_the_extractor_cannot(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    pinned = facts.add(story, "Rowan Hale", "is allergic to shellfish.", 1)
    session.add(pinned)
    await session.commit()

    assert facts.retire([pinned], pinned.id.hex[:8], 1) is None  # the extractor's way: refused
    response = await client.delete(f"/stories/{story.id}/facts/{pinned.id}")

    assert response.status_code == 200
    assert response.json()["valid_to_sequence"] is not None
    assert response.json()["pinned"] is True


async def test_retiring_twice_changes_nothing(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    fact = facts.add(story, "Isaure", "distrusts Rowan.", 1, model="m")
    session.add(fact)
    await session.commit()
    await a_message(session, story, "Later.", Role.USER)
    await session.commit()

    first = (await client.delete(f"/stories/{story.id}/facts/{fact.id}")).json()
    await a_message(session, story, "Later still.", Role.USER)
    await session.commit()
    second = (await client.delete(f"/stories/{story.id}/facts/{fact.id}")).json()

    assert first["valid_to_sequence"] == 2
    assert second["valid_to_sequence"] == 2


async def test_a_fact_of_another_story_is_a_404(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    other = await a_played_story(session)
    fact = facts.add(other, "Pell", "limps.", 1, model="m")
    session.add(fact)
    await session.commit()

    response = await client.delete(f"/stories/{story.id}/facts/{fact.id}")

    assert response.status_code == 404
    assert fact.valid_to_sequence is None


async def test_a_blank_fact_is_refused(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    story = await a_played_story(session)

    blank = await client.post(f"/stories/{story.id}/facts", json={"subject": "Pell", "text": "  "})
    nameless = await client.post(
        f"/stories/{story.id}/facts", json={"subject": "", "text": "limps."}
    )

    assert blank.status_code == 422
    assert nameless.status_code == 422


async def test_the_fact_command_pins_under_the_character_and_stores_no_turn(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "/fact keeps a knife under the counter")

    assert streamed.done["kind"] == "said"
    assert streamed.done["text"].startswith("Pinned under The Gilded Heron.")
    [fact] = (await client.get(f"/stories/{story.id}/facts")).json()
    assert (fact["subject"], fact["text"], fact["pinned"]) == (
        "The Gilded Heron",
        "keeps a knife under the counter",
        True,
    )
    assert len(await messages(session, story, hidden=True)) == 1
    assert model.calls == []


async def test_a_bare_fact_command_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "/fact")

    assert streamed.status == 422
    assert "/fact <statement>" in streamed.last[1]["detail"]
