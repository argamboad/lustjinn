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


# --- /do ------------------------------------------------------------------------------------------


async def test_a_direction_alone_writes_the_next_beat_under_it_with_no_reader_message(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Mags gathers the cards and leaves without a word.")

    streamed = await send(client, story.id, "/do have Mags leave the table")

    assert streamed.done["sent"] is None
    assert streamed.done["reply"]["text"].startswith("Mags gathers")
    assert instruction_sent(model) == {
        "role": "user",
        "content": directions.DIRECTION_FRAME + "have Mags leave the table",
    }
    assert directions.CARRY_ON not in instruction_sent(model)["content"]  # replaced, not joined
    stored = await messages(session, story, hidden=True)
    assert [m.role for m in stored] == [Role.ASSISTANT, Role.ASSISTANT]
    assert not any("have Mags leave" in m.text for m in stored)


async def test_a_direction_over_a_message_sends_the_message_and_stores_only_that(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("She names a price.")

    streamed = await send(
        client, story.id, '/do she asks for twice the usual\n\n"How much for the week?"'
    )

    assert streamed.done["sent"]["text"] == '"How much for the week?"'
    stored = await messages(session, story)
    assert [m.text for m in stored][1:] == ['"How much for the week?"', "She names a price."]
    assert not any("twice the usual" in m.text for m in stored)
    # The history ends on the reader's turn, so the direction goes as `system`.
    assert instruction_sent(model) == {
        "role": "system",
        "content": directions.DIRECTION_FRAME + "she asks for twice the usual",
    }
    assert model.last["messages"][-2] == {"role": "user", "content": '"How much for the week?"'}


async def test_a_direction_may_run_to_several_lines_before_the_blank_one(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    await send(client, story.id, "/do slow down\nlet the room breathe\n\nI sit.")

    assert instruction_sent(model)["content"].endswith("slow down\nlet the room breathe")
    assert (await messages(session, story))[-2].text == "I sit."


async def test_the_direction_is_part_of_what_is_asked_for(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """The same message twice under one direction is one turn, retried; under another it is a
    new ask."""
    story = await a_played_story(session)
    model.fails().says("Hm.").says("Hm again.")

    first = await send(client, story.id, "/do keep it short\n\nI sit.")
    retried = await send(client, story.id, "/do keep it short\n\nI sit.")
    other = await send(client, story.id, "/do make it long\n\nI sit.")

    assert first.error["sent"]["text"] == "I sit."
    assert retried.done["sent"]["id"] == first.error["sent"]["id"]  # found, not stored again
    assert other.done["sent"]["id"] != first.error["sent"]["id"]
    assert len(model.calls) == 3


async def test_a_bare_do_is_refused_with_its_usage(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "/do")

    assert streamed.status == 422
    assert "/do <direction>" in streamed.last[1]["detail"]
    assert model.calls == []


def test_the_split_is_on_the_first_blank_line() -> None:
    assert directions.split("have Mags leave") == ("have Mags leave", "")
    assert directions.split('slow down\n\n"Hello."\n\nMore.') == ("slow down", '"Hello."\n\nMore.')
    assert directions.split("  one line\nand two  \n\n  said  ") == ("one line\nand two", "said")


# --- /focus ---------------------------------------------------------------------------------------


async def test_focus_hands_the_turn_to_a_named_character_and_stores_no_command(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Mags looks up from the cards for the first time all night.")

    streamed = await send(client, story.id, "/focus Mags")

    assert streamed.done["sent"] is None
    assert streamed.done["reply"]["text"].startswith("Mags looks up")
    sent = instruction_sent(model)
    assert sent["role"] == "user"
    assert "Give this turn to Mags." in sent["content"]
    assert "Let them carry it" in sent["content"]
    assert "never write the user's words, actions or thoughts" in sent["content"]
    stored = await messages(session, story, hidden=True)
    assert [m.role for m in stored] == [Role.ASSISTANT, Role.ASSISTANT]
    assert not any("focus" in m.text.lower() for m in stored)


async def test_a_bare_focus_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "/focus")

    assert streamed.status == 422
    assert "/focus <who>" in streamed.last[1]["detail"]
    assert model.calls == []
