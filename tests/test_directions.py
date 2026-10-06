"""Turns the reader asks for without writing one: carry on, `/do`, `/focus`. Each sends a
framed direction as the prompt's last layer, and none of them puts a word into `messages`."""

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import directions
from lustjinn.models import Role, SpendKind
from tests.scripted_model import ScriptedModel
from tests.streaming import Streamed, send, stream
from tests.test_reroll import reroll
from tests.test_turns import a_played_story, ledger, messages


async def carry_on(client: httpx2.AsyncClient, story_id: object) -> Streamed:
    return await stream(client, f"/stories/{story_id}/continue")


def instruction_sent(model: ScriptedModel) -> dict[str, str]:
    """The prompt's last message: where a direction goes."""
    return model.last["messages"][-1]


# --- carry on -------------------------------------------------------------------------------------


async def test_carrying_on_adds_one_reply_and_one_ledger_row_and_no_reader_message(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Hello.").says(
        "The fire settles. Pell comes through with wood, and does not look up."
    )
    await send(client, story.id, "I wait.")

    streamed = await carry_on(client, story.id)

    done = streamed.done
    assert done["kind"] == "turn"
    assert done["sent"] is None
    assert done["reply"]["text"].startswith("The fire settles.")
    roles = [m.role for m in await messages(session, story)]
    assert roles == [Role.ASSISTANT, Role.USER, Role.ASSISTANT, Role.ASSISTANT]
    rows = await ledger(session, story)
    assert [row.kind for row in rows] == [SpendKind.REPLY, SpendKind.REPLY]


async def test_carrying_on_tells_the_model_not_to_wait_as_a_user_turn(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """The history ends on a reply, so the direction goes as `user`: two assistant turns in a
    row is a shape a model has never seen."""
    story = await a_played_story(session)
    model.says("The fire settles.")

    await carry_on(client, story.id)

    assert instruction_sent(model) == {"role": "user", "content": directions.CARRY_ON}
    assert "does not wait" in directions.CARRY_ON
    assert "never write their words, actions or thoughts" in directions.CARRY_ON
    before = model.last["messages"][-2]
    assert before["role"] == "assistant"  # the opening; nothing from the reader in between


async def test_a_carried_on_reply_can_be_rerolled_like_any_other(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First beat.").says("Second beat.")
    await carry_on(client, story.id)

    streamed = await reroll(client, story.id)

    assert streamed.done["reply"]["text"] == "Second beat."
    visible = [m.text for m in await messages(session, story)]
    assert visible[1:] == ["Second beat."]


async def test_a_carry_on_the_model_refuses_stores_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.fails()

    streamed = await carry_on(client, story.id)

    assert streamed.error["sent"] is None
    assert len(await messages(session, story, hidden=True)) == 1
    assert await ledger(session, story) == []


async def test_carrying_on_needs_a_story_that_exists(client: httpx2.AsyncClient) -> None:
    missing = "01a10d31-0000-7000-8000-000000000000"

    assert (await client.post(f"/stories/{missing}/continue")).status_code == 404
