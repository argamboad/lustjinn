"""Retrieval: what was said, found again among the turns a summary has already compressed.

The test embedder turns a text into a vector that says which of four keywords it contains, so
"the knife" and "a knife on the table" are near and "the harbour" is far from both.
"""

from collections.abc import Callable

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.context import MEMORIES_FRAME
from lustjinn.memory import BACKFILL_AT_MOST
from lustjinn.models import Embedding, Message, Role, SpendKind, Story, Summary
from lustjinn.settings import Settings
from tests.factories import a_message, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_turns import a_played_story, ledger

PLAIN = "The fog pressed against the windows and nobody looked up from their cards. "


async def a_compressed_story(session: AsyncSession, turns: list[str]) -> Story:
    """The dummy story whose first `turns` (after the opening) are already covered by a summary,
    followed by three recent turns. Nothing has been embedded yet."""
    story = await a_played_story(session)
    for i, text in enumerate(turns):
        await a_message(session, story, text, Role.USER if i % 2 == 0 else Role.ASSISTANT)
    last_covered = 1 + len(turns)
    session.add(
        Summary(
            story_id=story.id,
            from_sequence=1,
            to_sequence=last_covered,
            text="Earlier: Rowan arrived, took a room, and the evening wore on. " * 3,
            message_count=last_covered,
        )
    )
    for i in range(3):
        await a_message(
            session, story, f"Recent {i + 1}. {PLAIN}", Role.ASSISTANT if i % 2 else Role.USER
        )
    await session.commit()
    return story


async def embedded(session: AsyncSession, story: Story) -> list[int]:
    """The sequence numbers of the story's embedded messages."""
    rows = await session.scalars(
        select(Message.sequence)
        .join(Embedding, Embedding.message_id == Message.id)
        .where(Message.story_id == story.id)
        .order_by(Message.sequence)
    )
    return list(rows)


def memories_sent(model: ScriptedModel) -> str | None:
    return next(
        (m["content"] for m in model.last["messages"] if m["content"].startswith(MEMORIES_FRAME)),
        None,
    )


async def test_only_compressed_turns_are_embedded(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, [f"Turn {i}. {PLAIN}" for i in range(6)])
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    assert await embedded(session, story) == [1, 2, 3, 4, 5, 6, 7]  # the opening and six turns
    [first_call] = model.embedding_calls[:1]
    assert len(first_call) == 7
    assert not any("Recent" in text for text in first_call)


async def test_a_relevant_compressed_turn_is_recalled_into_the_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(
        session, ["I set the knife on the table.", "*Isaure did not look at the knife.*", PLAIN]
    )
    model.says("Hm.")

    await send(client, story.id, "Where did I leave the knife?")

    memories = memories_sent(model)
    assert memories is not None
    assert "[2] Rowan Hale: I set the knife on the table." in memories
    assert "[3] The Gilded Heron: *Isaure did not look at the knife.*" in memories
    assert PLAIN.strip() not in memories  # nothing in common with the question


async def test_recalled_turns_sit_after_the_transcript(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, ["I set the knife on the table.", PLAIN])
    model.says("Hm.")

    await send(client, story.id, "The knife?")

    contents = [m["content"] for m in model.last["messages"]]
    recent_at = max(i for i, c in enumerate(contents) if c.startswith("Recent"))
    memories_at = next(i for i, c in enumerate(contents) if c.startswith(MEMORIES_FRAME))
    assert recent_at < memories_at < len(contents)
    assert model.last["messages"][memories_at]["role"] == "system"


async def test_the_recall_count_is_a_ceiling(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
) -> None:
    tune(recall_count=1)
    story = await a_compressed_story(session, [f"Turn {i} with the knife. " for i in range(8)])
    model.says("Hm.")

    await send(client, story.id, "The knife.")

    memories = memories_sent(model)
    assert memories is not None
    assert len(memories.splitlines()) == 2  # the heading and one turn


async def test_nothing_below_the_threshold_is_recalled(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, [PLAIN, PLAIN, PLAIN])
    model.says("Hm.")

    await send(client, story.id, "Where is the knife?")

    assert memories_sent(model) is None


async def test_the_question_asked_is_the_readers_last_message(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, ["Silver on the dock.", "Ferrin and a knife."])
    model.says("Hm.")

    await send(client, story.id, "Tell me about the silver.")

    assert model.embedding_calls[-1] == ["Tell me about the silver."]
    memories = memories_sent(model)
    assert memories is not None
    assert "Silver on the dock." in memories
    assert "Ferrin" not in memories


async def test_an_embedding_endpoint_that_is_down_does_not_cost_the_reader_a_reply(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, ["I set the knife on the table."])
    model.embedder_down = True
    model.says("Hm.")

    streamed = await send(client, story.id, "The knife?")

    assert streamed.done["reply"]["text"] == "Hm."
    assert memories_sent(model) is None
    assert await embedded(session, story) == []
    assert [row.kind for row in await ledger(session, story)] == [SpendKind.REPLY]


async def test_a_backfill_takes_at_most_128_turns_per_call(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, [f"Turn {i}. {PLAIN}" for i in range(150)])
    model.says("Hm.").says("Hm again.")

    await send(client, story.id, "I come in.")
    first = await embedded(session, story)
    await send(client, story.id, "I come in again.")

    assert len(first) == BACKFILL_AT_MOST
    assert first == list(range(1, BACKFILL_AT_MOST + 1))  # the oldest first
    assert len(await embedded(session, story)) == 151  # the rest on the next turn
    assert len(model.embedding_calls[0]) == BACKFILL_AT_MOST


async def test_a_turn_already_embedded_is_not_embedded_again(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, ["One.", "Two."])
    model.says("Hm.").says("Hm.")

    await send(client, story.id, "First.")
    await send(client, story.id, "Second.")

    backfills = [call for call in model.embedding_calls if len(call) > 1]
    assert len(backfills) == 1


async def test_without_an_embedding_model_nothing_is_embedded_or_recalled(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
) -> None:
    tune(embedding_model=None)
    story = await a_compressed_story(session, ["I set the knife on the table."])
    model.says("Hm.")

    await send(client, story.id, "The knife?")

    assert model.embedding_calls == []
    assert memories_sent(model) is None


async def test_a_story_with_nothing_compressed_asks_for_no_embeddings(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    await send(client, story.id, "The knife?")

    assert model.embedding_calls == []


async def test_a_wrong_dimension_is_refused_and_costs_the_reader_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_compressed_story(session, ["I set the knife on the table."])
    model.embedding_dimensions = 768
    model.says("Hm.")

    streamed = await send(client, story.id, "The knife?")

    assert streamed.done["reply"]["text"] == "Hm."
    assert await embedded(session, story) == []


async def test_the_store_holds_vectors_of_one_length_only(session: AsyncSession) -> None:
    story = await a_story(session)
    message = await a_message(session, story, "x")
    session.add(
        Embedding(message_id=message.id, story_id=story.id, vector=[0.1, 0.2, 0.3], model="m")
    )

    # pgvector's own check, surfacing as the driver's error: the column knows its length.
    with pytest.raises(DBAPIError, match="expected 1536 dimensions"):
        await session.flush()
