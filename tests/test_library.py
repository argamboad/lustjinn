"""The library: three shelves behind one set of endpoints, and the rules on names, deleting
and the default persona."""

from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.context import PERSONA_FRAME
from lustjinn.library import Slug
from lustjinn.models import AppSettings, Character, Persona, Snippet, Story, new_id
from scripts.seed_dummy import seed
from tests.factories import a_character, a_persona, a_snippet, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send

Json = dict[str, Any]
SHELVES: list[Slug] = ["characters", "personas", "snippets"]


async def create(client: httpx2.AsyncClient, shelf: str, **body: object) -> Json:
    response = await client.post(f"/library/{shelf}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("shelf", SHELVES)
async def test_an_entry_can_be_created_read_listed_and_deleted(
    client: httpx2.AsyncClient, shelf: Slug
) -> None:
    created = await create(client, shelf, name="elena", text="You are Elena.")

    assert created["name"] == "elena"
    assert created["text"] == "You are Elena."
    assert created["version"] == 1
    assert created["used_by"] == []
    assert created["opening"] is None
    read = (await client.get(f"/library/{shelf}/{created['id']}")).json()
    assert read == created
    [listed] = (await client.get(f"/library/{shelf}")).json()
    assert (listed["id"], listed["name"], listed["preview"]) == (
        created["id"],
        "elena",
        "You are Elena.",
    )
    assert "text" not in listed  # a list does not carry every card whole
    assert (await client.delete(f"/library/{shelf}/{created['id']}")).status_code == 204
    assert (await client.get(f"/library/{shelf}/{created['id']}")).status_code == 404
    assert (await client.get(f"/library/{shelf}")).json() == []


async def test_a_character_carries_its_opening_and_a_blank_one_is_none(
    client: httpx2.AsyncClient,
) -> None:
    with_one = await create(
        client, "characters", name="Elena", text="A card.", opening="*Rain against the glass.*"
    )
    without = await create(client, "characters", name="Mira", text="A card.", opening="  ")

    assert with_one["opening"] == "*Rain against the glass.*"
    assert without["opening"] is None


@pytest.mark.parametrize("shelf", ["personas", "snippets"])
async def test_only_a_character_has_an_opening(client: httpx2.AsyncClient, shelf: str) -> None:
    response = await client.post(
        f"/library/{shelf}", json={"name": "x", "text": "t", "opening": "An opening."}
    )

    assert response.status_code == 422
    assert "has no opening" in response.json()["detail"]


@pytest.mark.parametrize("shelf", SHELVES)
async def test_a_name_already_on_the_shelf_is_refused_whatever_its_case(
    client: httpx2.AsyncClient, shelf: Slug
) -> None:
    """Create silently becoming replace would destroy a page of the reader's own writing."""
    await create(client, shelf, name="elena", text="the original")

    response = await client.post(f"/library/{shelf}", json={"name": "ELENA", "text": "an accident"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    [kept] = (await client.get(f"/library/{shelf}")).json()
    assert kept["preview"] == "the original"


@pytest.mark.parametrize("name", ["  ", "a/b", "con:trol", "what?", "a\tb", "x" * 201])
async def test_a_name_that_cannot_be_a_name_is_refused(
    client: httpx2.AsyncClient, name: str
) -> None:
    response = await client.post("/library/characters", json={"name": name, "text": "t"})

    assert response.status_code == 422


@pytest.mark.parametrize("name", ["rain storm", "storm!", "x" * 33, "ünder"])
async def test_a_snippets_name_must_be_typeable_as_one_word(
    client: httpx2.AsyncClient, name: str
) -> None:
    response = await client.post("/library/snippets", json={"name": name, "text": "t"})

    assert response.status_code == 422
    assert ":name" in response.json()["detail"]


async def test_a_snippets_name_may_have_the_characters_a_trigger_can_carry(
    client: httpx2.AsyncClient,
) -> None:
    created = await create(client, "snippets", name="rain_storm+2-b", text="t")

    assert created["name"] == "rain_storm+2-b"


async def test_names_are_trimmed_and_text_cannot_be_empty(client: httpx2.AsyncClient) -> None:
    created = await create(client, "personas", name="  Traveller ", text="A traveller.")

    assert created["name"] == "Traveller"
    empty = await client.post("/library/personas", json={"name": "x", "text": ""})
    assert empty.status_code == 422


async def test_names_starting_with_an_underscore_are_kept_but_not_listed(
    client: httpx2.AsyncClient,
) -> None:
    """Working papers — a template, notes towards a character — sit beside what they are about."""
    await create(client, "characters", name="_template", text="[ fill in ]")
    await create(client, "characters", name="Elena", text="A card.")

    listed = (await client.get("/library/characters")).json()
    everything = (await client.get("/library/characters", params={"hidden": "true"})).json()

    assert [e["name"] for e in listed] == ["Elena"]
    assert [(e["name"], e["hidden"]) for e in everything] == [("_template", True), ("Elena", False)]


async def test_the_shelf_is_listed_alphabetically_without_regard_to_case(
    client: httpx2.AsyncClient,
) -> None:
    for name in ["zoe", "Elena", "mira"]:
        await create(client, "personas", name=name, text="t")

    assert [e["name"] for e in (await client.get("/library/personas")).json()] == [
        "Elena",
        "mira",
        "zoe",
    ]


async def test_the_order_does_not_depend_on_the_servers_own_sorting_rules(
    client: httpx2.AsyncClient,
) -> None:
    """Punctuation, digits, then letters, an accent beside its base letter. A database created
    with one locale ignores a leading underscore and another puts `Á` after `Z`; the shelf asks
    for its order by name instead of taking the server's."""
    for name in ["Zoe", "Elena", "_template", "Ángela", "alba", "9lives"]:
        await create(client, "characters", name=name, text="t")

    everything = (await client.get("/library/characters", params={"hidden": "true"})).json()

    assert [e["name"] for e in everything] == [
        "_template",
        "9lives",
        "alba",
        "Ángela",
        "Elena",
        "Zoe",
    ]


async def test_a_shelf_that_does_not_exist_is_refused(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/library/openings")).status_code == 422
    assert (await client.get(f"/library/characters/{new_id()}")).status_code == 404


async def test_saving_changes_only_what_was_given(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session, name="Elena", opening="*Rain.*")
    await session.commit()

    url = f"/library/characters/{character.id}"

    renamed = (await client.patch(url, json={"version": 1, "name": "Elena Vance"})).json()
    assert (renamed["name"], renamed["text"], renamed["opening"]) == (
        "Elena Vance",
        "You are Elena.",
        "*Rain.*",
    )

    retexted = (await client.patch(url, json={"version": 2, "text": "A new card."})).json()
    assert (retexted["name"], retexted["text"], retexted["opening"]) == (
        "Elena Vance",
        "A new card.",
        "*Rain.*",
    )

    cleared = (await client.patch(url, json={"version": 3, "opening": None})).json()
    assert cleared["opening"] is None
    assert cleared["text"] == "A new card."


async def test_renaming_onto_another_entrys_name_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    await a_persona(session, name="Traveller")
    other = await a_persona(session, name="Keeper")
    await session.commit()

    response = await client.patch(
        f"/library/personas/{other.id}", json={"version": 1, "name": "TRAVELLER"}
    )

    assert response.status_code == 409
    same = await client.patch(
        f"/library/personas/{other.id}", json={"version": 1, "name": "keeper"}
    )
    assert same.status_code == 200  # a change of case on its own name is fine
    assert same.json()["name"] == "keeper"


async def test_renaming_a_character_a_story_uses_reaches_the_story(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """A story holds the id, not the name, so renaming is free — and editing the card reaches
    the story from its next turn."""
    character = await a_character(session, name="Elena")
    story = await a_story(session, character, name="Vardhal")
    await session.commit()

    await client.patch(
        f"/library/characters/{character.id}",
        json={
            "version": 1,
            "name": "Elena Vance",
            "text": "You are Elena Vance, keeper of the light.",
        },
    )

    opened = (await client.get(f"/stories/{story.id}")).json()
    assert opened["character_name"] == "Elena Vance"
    model.says("Hm.")
    await send(client, story.id, "Hello.")
    assert model.last["messages"][0]["content"] == "You are Elena Vance, keeper of the light."


async def test_an_entry_a_live_story_uses_is_not_deleted_and_the_stories_are_named(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session, name="Elena")
    await a_story(session, character, name="Vardhal")
    await a_story(session, character, name="Coast road")
    await a_story(session, await a_character(session, name="Mira"), name="Unrelated")
    await session.commit()

    response = await client.delete(f"/library/characters/{character.id}")

    assert response.status_code == 409
    assert "Coast road, Vardhal" in response.json()["detail"]
    read = (await client.get(f"/library/characters/{character.id}")).json()
    assert read["used_by"] == ["Coast road", "Vardhal"]


async def test_the_database_refuses_the_delete_even_when_only_a_deleted_story_uses_it(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    """A deleted story no longer counts as a user — but its row still points at the character,
    and the foreign key does not know the difference. Erasing it for good is step 7."""
    character = await a_character(session, name="Elena")
    story = await a_story(session, character)
    story.deleted_at = datetime.now(UTC)
    await session.commit()
    character_id = character.id  # the refused delete rolls the shared session back

    assert (await client.get(f"/library/characters/{character_id}")).json()["used_by"] == []
    response = await client.delete(f"/library/characters/{character_id}")

    assert response.status_code == 409
    assert "deleted story" in response.json()["detail"]
    assert await session.get(Character, character_id) is not None


async def test_the_foreign_key_is_what_refuses_in_the_end(session: AsyncSession) -> None:
    character = await a_character(session)
    await a_story(session, character)

    await session.delete(character)

    with pytest.raises(IntegrityError, match="fk_stories_character_id_characters"):
        await session.flush()


async def test_a_persona_is_looked_up_in_its_own_column(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    character = await a_character(session, name="allan")
    persona = await a_persona(session, name="elena")
    session.add(Story(name="Vardhal", character_id=character.id, persona_id=persona.id))
    await session.commit()

    assert (await client.get(f"/library/personas/{persona.id}")).json()["used_by"] == ["Vardhal"]
    assert (await client.delete(f"/library/personas/{persona.id}")).status_code == 409


async def test_a_snippet_is_used_by_no_story_and_can_always_go(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    snippet = await a_snippet(session)
    await session.commit()

    assert (await client.delete(f"/library/snippets/{snippet.id}")).status_code == 204
    assert await session.get(Snippet, snippet.id) is None


async def test_the_default_persona_is_set_read_and_cleared(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    persona = await a_persona(session, name="Keeper")
    await session.commit()

    assert (await client.get("/library/settings")).json() == {
        "default_persona_id": None,
        "default_persona_name": None,
    }
    chosen = await client.put("/library/settings", json={"default_persona_id": str(persona.id)})
    assert chosen.json() == {
        "default_persona_id": str(persona.id),
        "default_persona_name": "Keeper",
    }
    cleared = await client.put("/library/settings", json={"default_persona_id": None})
    assert cleared.json()["default_persona_id"] is None
    missing = await client.put("/library/settings", json={"default_persona_id": str(new_id())})
    assert missing.status_code == 422


async def test_the_default_persona_counts_as_used_by_every_story_that_names_none(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    keeper = await a_persona(session, name="Keeper")
    allan = await a_persona(session, name="Allan")
    character = await a_character(session)
    session.add(Story(name="The headland", character_id=character.id))  # names no persona
    session.add(Story(name="Named", character_id=character.id, persona_id=allan.id))
    session.add(AppSettings(default_persona_id=keeper.id))
    await session.commit()

    read = (await client.get(f"/library/personas/{keeper.id}")).json()
    assert read["used_by"] == ["The headland"]
    refused = await client.delete(f"/library/personas/{keeper.id}")
    assert refused.status_code == 409
    assert "The headland" in refused.json()["detail"]


async def test_deleting_the_default_persona_nobody_plays_as_clears_the_default(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    keeper = await a_persona(session, name="Keeper")
    session.add(AppSettings(default_persona_id=keeper.id))
    await session.commit()

    assert (await client.delete(f"/library/personas/{keeper.id}")).status_code == 204

    settings = await session.get(AppSettings, 1, populate_existing=True)
    assert settings is not None
    assert settings.default_persona_id is None


async def test_a_story_that_names_no_persona_plays_as_the_default(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    keeper = await a_persona(session, name="Keeper")
    keeper.text = "The keeper of the light."
    story = await a_story(session, await a_character(session))
    session.add(AppSettings(default_persona_id=keeper.id))
    await session.commit()
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert model.last["messages"][1] == {
        "role": "system",
        "content": PERSONA_FRAME + "The keeper of the light.",
    }


async def test_a_story_with_its_own_persona_keeps_it_over_the_default(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    keeper = await a_persona(session, name="Keeper")
    own = await a_persona(session, name="Traveller")
    character = await a_character(session)
    story = Story(name="Vardhal", character_id=character.id, persona_id=own.id)
    session.add_all([story, AppSettings(default_persona_id=keeper.id)])
    await session.commit()
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert model.last["messages"][1]["content"].endswith("A traveller.")


async def test_with_no_default_a_story_that_names_no_persona_plays_as_nobody(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """Even with exactly one persona on the shelf: choosing it would be choosing who the reader
    is playing, and it would change the day a second one appeared."""
    await a_persona(session, name="Only one")
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert [m["role"] for m in model.last["messages"]] == ["system", "user"]


async def test_the_settings_table_holds_one_row(session: AsyncSession) -> None:
    session.add(AppSettings(id=2))

    with pytest.raises(IntegrityError, match="ck_settings_one_row"):
        await session.flush()


async def test_seeding_makes_the_dummy_persona_the_default_unless_one_is_chosen(
    session: AsyncSession,
) -> None:
    _, persona = await seed(session)
    settings = await session.get(AppSettings, 1)
    assert settings is not None
    assert settings.default_persona_id == persona.id

    other = await a_persona(session, name="Chosen")
    settings.default_persona_id = other.id
    await seed(session)
    assert settings.default_persona_id == other.id
    assert await session.scalar(select(Persona).where(Persona.name == "Chosen")) is not None
