"""A question asked out of character is not a turn: answered from the same prompt, stored apart,
billed, and never in any prompt after it."""

from decimal import Decimal

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Aside, Character, Message, Persona, Role, SpendKind, Story
from lustjinn.prompt import build
from tests.factories import a_character, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_turns import a_played_story, ledger, messages


async def asides(session: AsyncSession, story: Story) -> list[Aside]:
    return list(await session.scalars(select(Aside).where(Aside.story_id == story.id)))


async def test_asking_answers_the_question_and_adds_nothing_to_the_story(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("The story does not say where she lives.")

    streamed = await send(client, story.id, "/ask Where does Elena live?")

    assert streamed.text == "The story does not say where she lives."
    done = streamed.done
    assert done["kind"] == "aside"
    assert done["aside"]["question"] == "Where does Elena live?"
    assert done["aside"]["answer"] == "The story does not say where she lives."
    assert done["aside"]["sequence"] == 1  # the opening was the newest message
    assert len(await messages(session, story, hidden=True)) == 1
    [aside] = await asides(session, story)
    assert (aside.model, aside.provider) == ("test-model", "test-host")
    assert (aside.prompt_tokens, aside.completion_tokens) == (10, 5)


async def test_asking_is_billed_as_its_own_kind_of_spending(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """A billed call that left no trace would make the audit quietly stop adding up."""
    story = await a_played_story(session)
    model.says("She has not said.")

    await send(client, story.id, "/ask What has Elena not said out loud?")

    [row] = await ledger(session, story)
    assert row.kind is SpendKind.ASIDE
    assert row.message_id is None
    assert row.cost == Decimal("0.0002")


async def test_asking_sends_the_same_layers_a_turn_would_and_then_the_directive(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """A prefix, exactly: on a caching host the question is nearly free, and it is grounded in
    the same story the character is playing."""
    story = await a_played_story(session)
    model.says("She sits down.").says("The story does not say.")
    await send(client, story.id, "I sit next to her.")

    await send(client, story.id, "/ask How old is she?")

    turn, aside = model.calls
    assert aside["messages"][: len(turn["messages"])] == turn["messages"]
    reply, directive = aside["messages"][len(turn["messages"]) :]
    assert reply == {"role": "assistant", "content": "She sits down."}
    assert directive["role"] == "user"  # the transcript ends on a reply
    assert directive["content"].startswith("Step out of the scene")
    assert directive["content"].endswith("The question: How old is she?")


async def test_asking_runs_cold_and_short_with_reasoning_off(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Nothing says.")

    await send(client, story.id, "/ask How far is the rehearsal room?")

    assert model.last["temperature"] == 0.4
    assert model.last["max_tokens"] == 600
    assert model.last["reasoning"] == {"enabled": False}
    assert "frequency_penalty" not in model.last


async def test_a_story_on_its_own_model_asks_on_it_with_the_cold_setting_mapped(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_story(session, await a_character(session))
    story.model = "cognitivecomputations/dolphin-mistral-24b-venice-edition"
    await session.commit()
    model.says("Nothing says.")

    await send(client, story.id, "/ask Who is she?")

    assert model.last["model"] == story.model
    assert model.last["temperature"] == 0.15


async def test_a_failed_question_stores_nothing_and_bills_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.fails()

    streamed = await send(client, story.id, "/ask What is she thinking?")

    assert "The question was not answered" in streamed.error["detail"]
    assert streamed.error["sent"] is None
    assert await asides(session, story) == []
    assert await ledger(session, story) == []


async def test_the_answer_never_enters_a_later_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("She is thirty-four.").says("She looks up.")
    await send(client, story.id, "/ask How old is she?")

    await send(client, story.id, "I come in.")

    sent = "\n".join(m["content"] for m in model.last["messages"])
    assert "How old is she?" not in sent
    assert "thirty-four" not in sent


async def test_an_unknown_command_is_refused_without_a_call_and_nothing_is_stored(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "/aks How old is she?")

    assert streamed.status == 422
    detail = streamed.last[1]["detail"]
    assert "/aks is not a command" in detail
    assert "nothing was stored" in detail
    assert model.calls == []
    assert len(await messages(session, story, hidden=True)) == 1
    assert await asides(session, story) == []


async def test_a_command_without_its_argument_is_refused_with_the_usage(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "/ask")

    assert streamed.status == 422
    assert streamed.last[1]["detail"] == "Usage: /ask <question> — nothing was stored."
    assert model.calls == []


async def test_a_doubled_slash_sends_a_message_that_begins_with_one(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    streamed = await send(client, story.id, "//ask is what I would type on the other site")

    assert streamed.done["kind"] == "turn"
    assert streamed.done["sent"]["text"] == "/ask is what I would type on the other site"
    assert model.last["messages"][-1]["content"] == "/ask is what I would type on the other site"


async def test_the_asides_of_a_story_are_listed_newest_first(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First answer.").says("Second answer.")
    await send(client, story.id, "/ask One?")
    await send(client, story.id, "/ask Two?")

    listed = (await client.get(f"/stories/{story.id}/asides")).json()

    assert [(a["question"], a["answer"]) for a in listed] == [
        ("Two?", "Second answer."),
        ("One?", "First answer."),
    ]
    assert (await client.get(f"/stories/{story.id}/asides")).status_code == 200


async def test_a_deleted_story_has_no_asides_to_list(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.delete(f"/stories/{story.id}")

    assert (await client.get(f"/stories/{story.id}/asides")).status_code == 404


def test_an_instruction_after_a_reply_arrives_as_the_readers_turn() -> None:
    character = Character(name="Elena", card="You are Elena.")
    history = [Message(role=Role.USER, text="Hello."), Message(role=Role.ASSISTANT, text="Hi.")]

    built = build(character, None, history, instruction="Step out of the scene.")

    assert (built[-1].role, built[-1].content) == ("user", "Step out of the scene.")


def test_an_instruction_after_the_readers_own_turn_stays_a_system_note() -> None:
    """Two user turns in a row and a model tends to answer the second and forget the first."""
    character = Character(name="Elena", card="You are Elena.")
    persona = Persona(name="Traveller", text="A traveller.")
    history = [Message(role=Role.USER, text="Hello.")]

    built = build(character, persona, history, instruction="Keep it short.")

    assert [m.role for m in built] == ["system", "system", "user", "system"]
    assert built[-1].content == "Keep it short."
    assert build(character, persona, [], instruction="x")[-1].role == "system"
