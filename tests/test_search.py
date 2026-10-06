"""Search: the turn where something was actually said, across every story or inside one."""

from datetime import UTC, datetime

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Role
from lustjinn.search import MESSAGE_SCORE, NAME_SCORE, snippet
from scripts.seed_dummy import seed
from tests.factories import a_message, a_story
from tests.test_turns import a_played_story


async def two_stories(session: AsyncSession):
    """The dummy story with a few turns, and a second story on another character."""
    first = await a_played_story(session)
    await a_message(session, first, "I set the knife on the counter.", Role.USER)
    knife = await a_message(
        session, first, "She does not look at the knife. The knife waits.", Role.ASSISTANT
    )
    hidden = await a_message(session, first, "A knife, rerolled away.", Role.ASSISTANT)
    hidden.deleted_at = datetime.now(UTC)
    second = await a_story(session, name="The Knife Room")
    await a_message(session, second, "No blades here, only the fog.", Role.USER)
    await session.commit()
    return first, second, knife


async def search(client: httpx2.AsyncClient, **params: str | int):
    return await client.get("/search", params=params)


async def test_a_phrase_is_found_with_its_story_and_turn(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    first, _second, knife = await two_stories(session)

    response = await search(client, q="knife")

    assert response.status_code == 200
    results = response.json()
    assert results["searched"] == 2
    scopes = [(h["scope"], h["story_name"]) for h in results["hits"]]
    assert scopes[0] == ("name", "The Knife Room")  # a story named for it outranks the turns
    turns = [h for h in results["hits"] if h["scope"] == "message"]
    assert [h["sequence"] for h in turns] == [3, 2]  # newest first among equals
    best = turns[0]
    assert best["message_id"] == str(knife.id)
    assert best["story_id"] == str(first.id)
    assert best["speaker"] == "The Gilded Heron"
    assert best["occurrences"] == 2
    assert best["score"] == MESSAGE_SCORE + 10
    assert turns[1]["speaker"] == "Rowan Hale"  # the reader, by their persona
    assert results["hits"][0]["score"] == NAME_SCORE


async def test_hidden_turns_and_deleted_stories_are_not_searched(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    first, second, _knife = await two_stories(session)
    second.deleted_at = datetime.now(UTC)
    await session.commit()

    results = (await search(client, q="knife")).json()

    assert results["searched"] == 1
    assert all(h["story_id"] == str(first.id) for h in results["hits"])
    assert not any("rerolled" in h["snippet"] for h in results["hits"])


async def test_inside_one_story_only_its_turns_are_searched_with_a_longer_excerpt(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    first, _second, _knife = await two_stories(session)

    results = (await search(client, q="knife", story_id=str(first.id))).json()

    assert results["searched"] == 1
    assert all(h["scope"] == "message" for h in results["hits"])
    assert [h["sequence"] for h in results["hits"]] == [3, 2]
    missing = await search(client, q="knife", story_id="01a10d31-0000-7000-8000-000000000000")
    assert missing.status_code == 404


async def test_the_search_is_case_insensitive_and_like_characters_mean_themselves(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    first, _second, _knife = await two_stories(session)
    await a_message(
        session, first, "Fifty percent, she says: 50% and not a mark more.", Role.ASSISTANT
    )
    await session.commit()

    upper = (await search(client, q="KNIFE")).json()
    percent = (await search(client, q="50%")).json()
    underscore = (await search(client, q="50_")).json()

    assert len(upper["hits"]) == 3
    assert len(percent["hits"]) == 1
    assert underscore["hits"] == []


async def test_a_blank_phrase_is_refused(client: httpx2.AsyncClient) -> None:
    assert (await search(client, q="")).status_code == 422
    assert (await client.get("/search")).status_code == 422


async def test_the_list_is_capped(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    first, _second, _knife = await two_stories(session)
    for i in range(5):
        await a_message(session, first, f"knife {i}", Role.USER)
    await session.commit()

    results = (await search(client, q="knife", limit=2)).json()

    assert len(results["hits"]) == 2


def test_the_snippet_is_one_line_around_the_first_match() -> None:
    text = (
        "The fog pressed in.\n\n"
        + "Rain. " * 20
        + "Then the knife, at last, on the counter. "
        + "More. " * 20
    )
    index = text.index("knife")

    cut = snippet(text, index)

    assert cut.startswith("…")
    assert cut.endswith("…")
    assert "knife" in cut
    assert "\n" not in cut
    assert len(cut) <= 48 * 2 + 2
    assert snippet("Short line.", 0) == "Short line."


async def test_a_story_without_a_persona_names_the_reader_you_unless_a_default_is_set(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    await a_message(session, story, "the lantern", Role.USER)
    await session.commit()

    before = (await search(client, q="lantern")).json()
    await seed(session)  # sets the dummy persona as the default
    await session.commit()
    after = (await search(client, q="lantern")).json()

    assert before["hits"][0]["speaker"] == "You"
    assert after["hits"][0]["speaker"] == "Rowan Hale"
