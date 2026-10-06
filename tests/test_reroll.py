"""Rerolling a reply hides the old one, keeps it, and writes a new one in its place."""

from decimal import Decimal

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Role, SpendKind
from tests.factories import a_character, a_message, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import Streamed, send, stream
from tests.test_turns import a_played_story, ledger, messages


async def reroll(client: httpx2.AsyncClient, story_id: object) -> Streamed:
    return await stream(client, f"/stories/{story_id}/reroll")


async def test_rerolling_hides_the_old_reply_and_writes_a_new_one(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First version.").says("Second version.")
    await send(client, story.id, "Hello.")

    streamed = await reroll(client, story.id)

    assert streamed.text == "Second version."
    done = streamed.done
    assert done["sent"] is None
    assert done["reply"]["text"] == "Second version."
    visible = await messages(session, story)
    assert [m.text for m in visible][1:] == ["Hello.", "Second version."]
    everything = await messages(session, story, hidden=True)
    assert [m.text for m in everything][1:] == ["Hello.", "First version.", "Second version."]
    assert everything[2].deleted_at is not None  # hidden, still in the table
    assert everything[3].sequence == 4  # the hidden reply's number is not reused


async def test_the_superseded_reply_is_not_in_the_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """A model shown its last attempt writes it again."""
    story = await a_played_story(session)
    model.says("First version.").says("Second version.")
    await send(client, story.id, "Hello.")

    await reroll(client, story.id)

    assert model.last["messages"][-2] == {"role": "user", "content": "Hello."}  # then the reason
    assert all("First version." not in m["content"] for m in model.last["messages"])


async def test_a_rerolled_reply_is_still_on_the_bill(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """Hidden from the transcript, never from the ledger: both calls were charged."""
    story = await a_played_story(session)
    model.says("First version.").says("Second version.")
    await send(client, story.id, "Hello.")

    await reroll(client, story.id)

    rows = await ledger(session, story)
    assert [r.kind for r in rows] == [SpendKind.REPLY, SpendKind.REPLY]
    assert sum(r.cost or 0 for r in rows) == Decimal("0.0004")
    everything = await messages(session, story, hidden=True)
    assert {r.message_id for r in rows} == {everything[2].id, everything[3].id}


async def test_a_reroll_the_model_never_answers_gives_the_old_reply_back(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("The first one.")
    await send(client, story.id, "Hello.")
    model.fails()

    streamed = await reroll(client, story.id)

    error = streamed.error
    assert "did not answer" in error["detail"]
    assert "kept" not in error["detail"]  # nothing of the reader's was at stake
    assert error["sent"] is None
    # The reply was hidden before the call; a call that brought nothing back must not leave
    # the story shorter than it found it.
    visible = await messages(session, story)
    assert visible[-1].text == "The first one."
    assert visible[-1].deleted_at is None

    # And a second attempt still has something to write again.
    model.says("The second one.")
    assert (await reroll(client, story.id)).done["reply"]["text"] == "The second one."


async def test_there_is_nothing_to_reroll_before_a_reply(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_story(session, await a_character(session))
    await session.commit()

    empty = await reroll(client, story.id)
    await a_message(session, story, "Hello.", Role.USER)
    await session.commit()
    after_the_reader = await reroll(client, story.id)

    assert empty.status == 409
    assert after_the_reader.status == 409
    assert "Send a message first" in after_the_reader.last[1]["detail"]
    assert model.calls == []


async def test_the_opening_alone_is_not_rerolled_and_stays_as_written(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    refused = await reroll(client, story.id)

    assert refused.status == 409
    assert "opening" in refused.last[1]["detail"]
    assert model.calls == []
    [opening] = await messages(session, story, hidden=True)
    assert opening.deleted_at is None


async def test_a_beat_the_model_wrote_after_the_opening_can_be_rerolled_with_no_reader_turn(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """A beat the model wrote (carry on, step 7) is not the opening, even with no reader turn."""
    story = await a_played_story(session)
    beat = await a_message(session, story, "The keeper looks up.", Role.ASSISTANT)
    beat.model = "test-model"
    await session.commit()
    model.says("The keeper does not look up.")

    streamed = await reroll(client, story.id)

    assert streamed.done["reply"]["text"] == "The keeper does not look up."


async def test_a_deleted_story_has_nothing_to_reroll(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.delete(f"/stories/{story.id}")

    assert (await reroll(client, story.id)).status == 404
