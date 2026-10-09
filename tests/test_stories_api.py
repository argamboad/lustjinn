"""The stories API: create, list, open, rename, delete."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Message, Role, Story, new_id
from scripts.seed_dummy import Dummy, seed
from tests.factories import a_character, a_message, a_persona, a_story

Json = dict[str, Any]


async def create(client: httpx2.AsyncClient, **body: object) -> Json:
    response = await client.post("/stories", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_story_starts_on_its_characters_opening(
    client: httpx2.AsyncClient, session: AsyncSession, dummy: Dummy
) -> None:
    character, persona = await seed(session)

    story = await create(
        client, name="First night", character_id=str(character.id), persona_id=str(persona.id)
    )

    assert story["name"] == "First night"
    assert story["character_name"] == "The Gilded Heron"
    assert story["persona_name"] == "Rowan Hale"
    assert "model" not in story  # every story plays on the default model (#140)
    [opening] = story["messages"]
    assert (opening["sequence"], opening["role"], opening["text"]) == (
        1,
        "assistant",
        dummy.opening,
    )
    assert opening["model"] is None  # a person wrote it


async def test_a_character_with_no_opening_starts_an_empty_story(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session)

    story = await create(client, name="Blank page", character_id=str(character.id))

    assert story["messages"] == []
    assert story["persona_id"] is None
    assert story["last_message_at"] is None
    assert story["last_message_preview"] is None


async def test_the_name_is_trimmed_and_cannot_be_blank(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session)

    story = await create(client, name="  Vardhal  ", character_id=str(character.id))
    blank = await client.post("/stories", json={"name": "   ", "character_id": str(character.id)})

    assert story["name"] == "Vardhal"
    assert blank.status_code == 422


async def test_a_story_needs_a_character_that_exists(client: httpx2.AsyncClient) -> None:
    response = await client.post("/stories", json={"name": "X", "character_id": str(new_id())})

    assert response.status_code == 422
    assert response.json()["detail"] == "There is no character with that id."


async def test_a_story_cannot_name_a_persona_that_does_not_exist(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session)

    response = await client.post(
        "/stories",
        json={"name": "X", "character_id": str(character.id), "persona_id": str(new_id())},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "There is no persona with that id."


async def test_the_list_puts_the_story_played_most_recently_first(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    old = await a_story(session, name="Old favourite")
    new = await a_story(session, name="Started today")
    untouched = await a_story(session, name="Not begun")
    old.created_at = new.created_at = untouched.created_at = now - timedelta(days=30)
    (await a_message(session, new, "Earlier today.")).sent_at = now - timedelta(hours=3)
    (await a_message(session, old, "A minute ago.")).sent_at = now - timedelta(minutes=1)
    await session.commit()

    listed = (await client.get("/stories")).json()

    assert [story["name"] for story in listed] == ["Old favourite", "Started today", "Not begun"]
    assert listed[0]["last_message_preview"] == "A minute ago."
    assert listed[2]["last_message_at"] is None


async def test_the_list_carries_who_is_in_each_story(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session, name="Elena")
    persona = await a_persona(session, name="Traveller")
    session.add(Story(name="Vardhal", character_id=character.id, persona_id=persona.id))
    await session.commit()

    [story] = (await client.get("/stories")).json()

    assert (story["character_name"], story["persona_name"]) == ("Elena", "Traveller")


async def test_the_preview_is_the_start_of_the_newest_visible_message(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    await a_message(session, story, "The first thing said.")
    await a_message(session, story, "word " * 100)
    hidden = await a_message(session, story, "A reply that was rerolled away.")
    hidden.deleted_at = datetime.now(UTC)
    await session.commit()

    [listed] = (await client.get("/stories")).json()

    assert listed["last_message_preview"] == ("word " * 100)[:200]


async def test_opening_a_story_returns_its_messages_in_order_without_the_hidden_ones(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    await a_message(session, story, "One.", Role.USER)
    hidden = await a_message(session, story, "Two, rerolled away.", Role.ASSISTANT)
    hidden.deleted_at = datetime.now(UTC)
    await a_message(session, story, "Two, kept.", Role.ASSISTANT)
    await session.commit()

    opened = (await client.get(f"/stories/{story.id}")).json()

    assert [(m["sequence"], m["role"], m["text"]) for m in opened["messages"]] == [
        (1, "user", "One."),
        (3, "assistant", "Two, kept."),
    ]


async def test_a_story_can_be_renamed(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    story = await a_story(session, name="Untitled")
    await session.commit()

    response = await client.patch(f"/stories/{story.id}", json={"name": "  The long night "})

    assert response.status_code == 200
    assert response.json()["name"] == "The long night"
    assert (await client.get(f"/stories/{story.id}")).json()["name"] == "The long night"


async def test_deleting_a_story_hides_it_and_keeps_its_rows(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    message = await a_message(session, story, "Still on disk.")
    await session.commit()

    response = await client.delete(f"/stories/{story.id}")

    assert response.status_code == 204
    assert (await client.get("/stories")).json() == []
    assert (await client.get(f"/stories/{story.id}")).status_code == 404
    kept = await session.get(Story, story.id, populate_existing=True)
    assert kept is not None
    assert kept.deleted_at is not None
    assert await session.get(Message, message.id) is not None


async def test_a_deleted_story_cannot_be_renamed_or_deleted_again(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    await session.commit()
    await client.delete(f"/stories/{story.id}")

    assert (await client.patch(f"/stories/{story.id}", json={"name": "X"})).status_code == 404
    assert (await client.delete(f"/stories/{story.id}")).status_code == 404


async def test_a_story_that_never_existed_is_not_found(client: httpx2.AsyncClient) -> None:
    missing = new_id()

    assert (await client.get(f"/stories/{missing}")).status_code == 404
    assert (await client.patch(f"/stories/{missing}", json={"name": "X"})).status_code == 404
    assert (await client.delete(f"/stories/{missing}")).status_code == 404


async def test_an_id_that_is_not_an_id_is_refused(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/stories/not-an-id")).status_code == 422
