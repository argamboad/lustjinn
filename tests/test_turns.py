"""A turn: the reader's message is kept first; the reply streams back and is kept with its cost."""

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import turns
from lustjinn.context import PERSONA_FRAME
from lustjinn.main import app
from lustjinn.models import Message, Role, Spend, SpendKind, Story, new_id
from lustjinn.settings import Settings, get_settings
from scripts.seed_dummy import Dummy, seed
from tests.factories import a_character, a_message, a_persona, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send


async def messages(session: AsyncSession, story: Story, hidden: bool = False) -> list[Message]:
    """The story's messages in order; visible ones only unless `hidden` asks for all."""
    query = select(Message).where(Message.story_id == story.id).order_by(Message.sequence)
    if not hidden:
        query = query.where(Message.deleted_at.is_(None))
    return list(await session.scalars(query.execution_options(populate_existing=True)))


async def ledger(session: AsyncSession, story: Story) -> list[Spend]:
    return list(await session.scalars(select(Spend).where(Spend.story_id == story.id)))


async def a_played_story(session: AsyncSession) -> Story:
    """The dummy character with its opening, and the dummy persona."""
    character, persona = await seed(session)
    story = Story(name="First night", character_id=character.id, persona_id=persona.id)
    session.add(story)
    await session.flush()
    await a_message(session, story, character.opening or "", Role.ASSISTANT)
    await session.commit()
    return story


async def test_a_turn_streams_the_reply_and_keeps_both_sides(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("She looks up from the ledger, and does not smile.")

    streamed = await send(client, story.id, "I come in from the rain.")

    assert streamed.status == 200
    assert streamed.text == "She looks up from the ledger, and does not smile."
    done = streamed.done
    assert done["kind"] == "turn"
    assert done["sent"]["text"] == "I come in from the rain."
    assert done["sent"]["role"] == "user"
    assert done["reply"]["text"] == "She looks up from the ledger, and does not smile."
    assert done["reply"]["model"] == "test-model"
    assert done["reply"]["provider"] == "test-host"
    assert done["replayed"] is False

    _opening, sent, reply = await messages(session, story)
    assert (sent.sequence, sent.role, sent.model) == (2, Role.USER, None)
    assert (reply.sequence, reply.role) == (3, Role.ASSISTANT)
    assert (reply.model, reply.provider) == ("test-model", "test-host")
    assert (reply.prompt_tokens, reply.completion_tokens) == (10, 5)
    assert sent.request_hash is not None


async def test_every_billed_call_leaves_exactly_one_ledger_row(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("She looks up.")

    await send(client, story.id, "I come in.")

    [row] = await ledger(session, story)
    *_, reply = await messages(session, story)
    assert row.kind is SpendKind.REPLY
    assert row.message_id == reply.id
    assert row.cost == Decimal("0.0002")
    assert (row.prompt_tokens, row.completion_tokens, row.cached_tokens) == (10, 5, 4)
    assert (row.model, row.provider, row.generation_id) == ("test-model", "test-host", "gen-1")


async def test_a_call_the_api_did_not_price_is_recorded_as_unpriced(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says_unpriced("She looks up.")

    await send(client, story.id, "I come in.")

    [row] = await ledger(session, story)
    assert row.cost is None
    assert row.prompt_tokens == 10


async def test_the_prompt_is_the_card_the_persona_and_the_transcript_in_that_order(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, dummy: Dummy
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    assert model.last["messages"] == [
        {"role": "system", "content": dummy.card},
        {"role": "system", "content": PERSONA_FRAME + dummy.persona},
        {"role": "assistant", "content": dummy.opening},
        {"role": "user", "content": "I come in."},
    ]


async def test_a_story_with_no_persona_sends_no_frame(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert [m["role"] for m in model.last["messages"]] == ["system", "user"]


async def test_a_reply_is_asked_with_reasoning_off_and_the_configured_sampling(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert model.last["model"] == "deepseek/deepseek-v4-flash"
    assert model.last["reasoning"] == {"enabled": False}
    assert model.last["temperature"] == 1.0
    assert model.last["max_tokens"] == 1024
    assert "frequency_penalty" not in model.last


async def test_a_reply_may_reason_first_when_the_settings_allow_it(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    thinking = settings.model_copy(update={"think_before_replying": True})
    app.dependency_overrides[get_settings] = lambda: thinking
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert "reasoning" not in model.last


async def test_the_message_survives_a_model_that_fails(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """If the send were only stored after a successful reply, an outage would swallow it."""
    story = await a_played_story(session)
    model.fails()

    streamed = await send(client, story.id, "No esperaba encontrarte.")

    assert streamed.status == 200
    error = streamed.error
    assert "Your message was kept" in error["detail"]
    assert "Do not send it again" in error["detail"]
    assert "503" in error["detail"]
    assert error["sent"]["text"] == "No esperaba encontrarte."

    _opening, kept = await messages(session, story)
    assert (kept.role, kept.text) == (Role.USER, "No esperaba encontrarte.")
    assert await ledger(session, story) == []  # a call that failed is not a billed call


async def test_retrying_a_send_the_model_failed_does_not_store_it_twice(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """The case idempotency exists for: one turn, one retry, one row."""
    story = await a_played_story(session)
    model.fails().says("I could say the same about you.")

    first = await send(client, story.id, "Hello.")
    second = await send(client, story.id, "Hello.")

    assert first.last[0] == "error"
    assert second.done["reply"]["text"] == "I could say the same about you."
    found = await messages(session, story)
    assert [m.role for m in found] == [Role.ASSISTANT, Role.USER, Role.ASSISTANT]
    assert len(model.calls) == 2


async def test_the_same_words_after_a_reply_landed_are_a_genuinely_new_send(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """Saying "Hello." twice in one story is ordinary, not a retry: the anchor moved on."""
    story = await a_played_story(session)
    model.says("Una.").says("Two.")

    await send(client, story.id, "Hello.")
    await send(client, story.id, "Hello.")

    found = await messages(session, story)
    assert [m.text for m in found[1:]] == ["Hello.", "Una.", "Hello.", "Two."]
    assert len(model.calls) == 2


async def test_a_send_already_answered_is_returned_rather_than_replayed(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A true replay of the identical request — which only two copies of one request in flight
    can produce, since the anchor moves once a reply lands. Pinning the hash simulates it."""
    story = await a_played_story(session)

    def pinned(*_: object) -> str:
        return "PINNED"

    monkeypatch.setattr(turns, "request_hash", pinned)
    model.says("Una.")

    first = await send(client, story.id, "Hello.")
    replay = await send(client, story.id, "Hello.")

    assert replay.done["replayed"] is True
    assert replay.done["sent"]["id"] == first.done["sent"]["id"]
    assert replay.done["reply"]["text"] == "Una."
    assert replay.text == ""  # nothing streamed: nothing was written
    assert len(model.calls) == 1
    assert len(await messages(session, story)) == 3


async def test_resending_words_the_reader_deleted_puts_them_back_in_the_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """A real story: the reader deleted their last turn and pasted it again. The hash matched
    the tombstone, the send was taken for a retry of it, and the prompt was built from the
    visible messages only — so the model kept answering the story without that turn."""
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("One.").says("Two.").says("Two, again.")
    await send(client, story.id, "Primera.")
    await send(client, story.id, "Segunda.")
    *_, deleted_turn, deleted_reply = await messages(session, story)
    deleted_turn.deleted_at = deleted_reply.deleted_at = datetime.now(UTC)
    await session.commit()

    streamed = await send(client, story.id, "Segunda.")

    assert streamed.done["reply"]["text"] == "Two, again."
    assert model.last["messages"][-1] == {"role": "user", "content": "Segunda."}
    visible = await messages(session, story)
    assert [m.text for m in visible] == ["Primera.", "One.", "Segunda.", "Two, again."]
    assert len(await messages(session, story, hidden=True)) == 6  # nothing was erased
    assert deleted_turn.request_hash is None  # the tombstone kept its text and lost its hash


async def test_a_reply_cut_off_at_the_ceiling_is_still_a_reply(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.truncated("It went on and")

    streamed = await send(client, story.id, "Hello.")

    assert streamed.done["reply"]["text"] == "It went on and"


async def test_a_reply_with_nothing_in_it_is_a_failure_and_is_not_billed(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.empty()

    streamed = await send(client, story.id, "Hello.")

    assert "no message content" in streamed.error["detail"]
    assert [m.role for m in await messages(session, story)] == [Role.ASSISTANT, Role.USER]
    assert await ledger(session, story) == []


async def test_a_blank_message_is_refused_before_anything_is_stored(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)

    streamed = await send(client, story.id, "   ")

    assert streamed.status == 422
    assert len(await messages(session, story)) == 1
    assert model.calls == []


async def test_a_story_that_does_not_exist_or_was_deleted_takes_no_turn(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_story(session)
    story.deleted_at = datetime.now(UTC)
    await session.commit()

    assert (await send(client, new_id(), "Hello.")).status == 404
    assert (await send(client, story.id, "Hello.")).status == 404
    assert model.calls == []


async def test_the_reply_is_the_newest_message_the_list_shows(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("She looks up.")

    await send(client, story.id, "I come in.")

    [listed] = (await client.get("/stories")).json()
    assert listed["last_message_preview"] == "She looks up."


def test_the_hash_is_the_first_32_hex_digits_of_sha256_over_story_anchor_and_text() -> None:
    story_id = uuid.UUID("0199b4b0-0000-7000-8000-000000000001")

    expected = hashlib.sha256(f"{story_id}|4|Hello.".encode()).hexdigest()[:32].upper()

    assert turns.request_hash(story_id, 4, "Hello.") == expected
    assert turns.request_hash(story_id, 5, "Hello.") != expected  # another anchor
    assert turns.request_hash(new_id(), 4, "Hello.") != expected  # another story


def test_the_same_words_under_two_directions_are_two_different_sends() -> None:
    """The direction (step 7) is part of what is asked for, so it is part of the identity."""
    story_id = new_id()

    plain = turns.request_hash(story_id, 0, "Say something.")
    short = turns.request_hash(story_id, 0, "Say something.", "Keep it short.")
    long = turns.request_hash(story_id, 0, "Say something.", "Take your time.")

    assert len({plain, short, long}) == 3
    assert turns.request_hash(story_id, 0, "Say something.", "  ") == plain
    assert turns.request_hash(story_id, 0, "Say something.", " Keep it short. ") == short


async def test_a_persona_and_character_can_be_told_apart_in_the_prompt_frame(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    character = await a_character(session, name="Elena")
    persona = await a_persona(session, name="Traveller")
    story = Story(name="Vardhal", character_id=character.id, persona_id=persona.id)
    session.add(story)
    await session.commit()
    model.says("Hm.")

    await send(client, story.id, "Hello.")

    assert model.last["messages"][1]["content"].startswith("The user is playing")
    assert model.last["messages"][1]["content"].endswith("A traveller.")


async def test_sequence_numbers_count_hidden_rows_too(session: AsyncSession) -> None:
    story = await a_story(session)
    hidden = await a_message(session, story, "Gone.")
    hidden.deleted_at = datetime.now(UTC)
    await session.flush()

    assert await turns._next_sequence(session, story.id) == 2  # pyright: ignore[reportPrivateUsage]
    assert await session.scalar(select(func.count()).select_from(Message)) == 1
