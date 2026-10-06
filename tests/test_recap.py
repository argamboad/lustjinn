"""`/recap`: a way back into a story after a break, without a model call."""

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Role, Summary
from lustjinn.recap import HEADING, MOST_RECAP_TURNS, RECAP_TURNS, count_from
from tests.factories import a_message, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_turns import a_played_story, ledger, messages


async def a_story_of(session: AsyncSession, turns: int):
    story = await a_played_story(session)
    for i in range(turns):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        await a_message(session, story, f"Turn {i + 2}.", role)
    await session.commit()
    return story


async def test_a_recap_shows_the_last_four_turns_and_stores_and_bills_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_story_of(session, 6)

    streamed = await send(client, story.id, "/recap")

    assert streamed.done["kind"] == "said"
    assert streamed.done["text"] == (
        f"{HEADING}\n\nThe last {RECAP_TURNS} turns:\n\n"
        "You:\nTurn 4.\n\nThe Gilded Heron:\nTurn 5.\n\nYou:\nTurn 6.\n\nThe Gilded Heron:\nTurn 7."
    )
    assert len(await messages(session, story, hidden=True)) == 7
    assert await ledger(session, story) == []
    assert model.calls == []


async def test_the_count_can_be_asked_for_and_is_clamped(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story_of(session, 30)

    two = (await send(client, story.id, "/recap 2")).done["text"]
    many = (await send(client, story.id, "/recap 500")).done["text"]
    one = (await send(client, story.id, "/recap 0")).done["text"]

    assert "The last 2 turns:" in two
    assert f"The last {MOST_RECAP_TURNS} turns:" in many
    assert "The last turn:" in one
    assert one.endswith("The Gilded Heron:\nTurn 31.")


async def test_a_word_is_refused_before_anything_happens(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story_of(session, 2)

    streamed = await send(client, story.id, "/recap some")

    assert streamed.status == 422
    assert streamed.last[1]["detail"] == (
        f"/recap takes a number of turns, up to {MOST_RECAP_TURNS} — nothing was stored."
    )


async def test_the_latest_summary_comes_first_under_earlier(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story_of(session, 4)
    session.add_all(
        [
            Summary(
                story_id=story.id, from_sequence=1, to_sequence=2, text="Old.", message_count=2
            ),
            Summary(
                story_id=story.id,
                from_sequence=3,
                to_sequence=4,
                text="Rowan took room seven.",
                message_count=2,
            ),
        ]
    )
    await session.commit()

    text = (await send(client, story.id, "/recap 1")).done["text"]

    assert text.startswith(f"{HEADING}\n\nEarlier:\nRowan took room seven.\n\nThe last turn:")
    assert "Old." not in text


async def test_a_story_with_nothing_said_says_so(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)  # a character without an opening: no messages at all
    await session.commit()

    text = (await send(client, story.id, "/recap")).done["text"]

    assert text == f"{HEADING}\n\nNothing has been said yet."


def test_the_count_is_read_and_clamped() -> None:
    assert count_from("") == RECAP_TURNS
    assert count_from(" 7 ") == 7
    assert count_from("0") == 1
    assert count_from("99") == MOST_RECAP_TURNS
    for word in ("four", "-1", "2.5"):
        with pytest.raises(ValueError, match="takes a number of turns"):
            count_from(word)
