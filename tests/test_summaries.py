"""Summaries: what happened, compressed in batches once the turns no longer fit.

Every test plays on the dummy character — a card the size of a real one — so the budget binds
the way it does in a real story.
"""

from collections.abc import Callable

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import memory, tokens
from lustjinn.memory import SUMMARY_INSTRUCTION, batch_to_compress, credible
from lustjinn.models import Message, Role, SpendKind, Story, Summary
from lustjinn.settings import Settings
from scripts.seed_dummy import Dummy
from tests.factories import a_message, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_turns import a_played_story, ledger

FILLER = (
    "The fog pressed against the windows and the dice went on rattling upstairs while the fire "
    "settled lower in the grate. Pell came through with an armful of wood and favoured his knee "
    "on the way back. At the corner table Blake turned a page of the manifest he was not "
    "reading and let his eyes rest on the door. "
)
"""About 70 tokens: a turn of ordinary length, long enough that a real summary compresses it."""


async def a_long_story(session: AsyncSession, turns: int) -> Story:
    """The dummy story with `turns` more exchanges after the opening, numbered."""
    story = await a_played_story(session)
    for i in range(turns):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        await a_message(session, story, f"Turn {i + 2}. {FILLER}", role)
    await session.commit()
    return story


async def summaries(session: AsyncSession, story: Story) -> list[Summary]:
    return list(
        await session.scalars(
            select(Summary).where(Summary.story_id == story.id).order_by(Summary.from_sequence)
        )
    )


def prompt_texts(model: ScriptedModel) -> list[str]:
    """What the reply call was sent (the last call), content only."""
    return [m["content"] for m in model.last["messages"]]


# Every summary is followed by a fact extraction (one more model call), so a scripted model
# that summarises must also answer `extracts()` before the reply.


def a_budget_that_holds(dummy: Dummy, turns: int, settings: Settings) -> int:
    """A budget with room for the fixed layers, the reply, and about `turns` turns."""
    fixed = tokens.for_message(dummy.card) + tokens.for_message(dummy.persona) + 40
    one_turn = tokens.for_message(FILLER) + 4
    return fixed + settings.max_tokens + memory.ROOM_FOR_THE_REPLY + turns * one_turn


async def test_a_conversation_that_fits_is_never_summarised(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_long_story(session, 10)
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    assert await summaries(session, story) == []
    assert [row.kind for row in await ledger(session, story)] == [SpendKind.REPLY]
    assert len(model.calls) == 1


async def test_turns_that_no_longer_fit_are_summarised_instead_of_dropped(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.summarises("Rowan arrived and took a room.").extracts().says("Hm.")

    streamed = await send(client, story.id, "I come in.")

    [summary] = await summaries(session, story)
    assert summary.from_sequence == 1  # the oldest turns went first
    assert memory.WORTH_A_CALL <= summary.message_count <= memory.AT_MOST_PER_SUMMARY
    assert summary.to_sequence < 31  # the newest turns stayed verbatim
    sent = prompt_texts(model)
    assert any(text.startswith("Rowan arrived and took a room.") for text in sent)
    assert not any("Turn 2." in text for text in sent)  # compressed, not sent raw
    assert "I come in." in sent  # the newest, always
    assert streamed.done["reply"]["text"] == "Hm."


async def test_the_summary_reaches_the_prompt_ahead_of_the_recent_turns(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.summarises("Earlier, Rowan arrived.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    roles = [m["role"] for m in model.last["messages"]]
    texts = prompt_texts(model)
    summary_at = next(i for i, t in enumerate(texts) if t.startswith("Earlier, Rowan arrived."))
    first_turn_at = next(i for i, t in enumerate(texts) if t.startswith("Turn "))
    assert roles[summary_at] == "system"
    assert summary_at < first_turn_at
    assert texts[0] == dummy.card  # the card still leads


async def test_already_summarised_turns_are_not_summarised_again(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.summarises("First stretch.").extracts().says("Hm.")
    await send(client, story.id, "I come in.")
    [first] = await summaries(session, story)

    # Many more turns, then another send: the next summary starts where the first stopped.
    for i in range(30):
        await a_message(
            session, story, f"Later {i}. {FILLER}", Role.ASSISTANT if i % 2 else Role.USER
        )
    await session.commit()
    model.summarises("Second stretch.").extracts().says("Hm.")
    await send(client, story.id, "I go upstairs.")

    first_again, second = await summaries(session, story)
    assert first_again.id == first.id
    assert second.from_sequence == first.to_sequence + 1
    sent = prompt_texts(model)
    both = next(text for text in sent if text.startswith("First stretch."))
    assert "\n\nSecond stretch." in both  # the two summaries, one layer, in order


async def test_compression_is_occasional_rather_than_a_toll_on_every_turn(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    """Compressing only the overflow ran every turn on two messages. A batch buys several
    turns of room."""
    tune(context_budget=a_budget_that_holds(dummy, 24, tune()))
    story = await a_long_story(session, 30)
    for i in range(8):
        model.summarises(f"Stretch {i}.").extracts().says(f"Reply {i}.")
        await send(client, story.id, f"Message {i}.")

    assert len(await summaries(session, story)) <= 4
    summary_calls = [c for c in model.calls if c["messages"][0]["content"] == SUMMARY_INSTRUCTION]
    assert len(summary_calls) <= 4


async def test_a_summariser_that_fails_sends_the_turns_whole_rather_than_forgetting_them(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    budget = a_budget_that_holds(dummy, 12, tune())
    tune(context_budget=budget)
    story = await a_long_story(session, 30)
    model.fails().fails().says("Hm.")  # the summary attempt, its retry, then the reply

    streamed = await send(client, story.id, "I come in.")

    assert streamed.done["reply"]["text"] == "Hm."
    assert await summaries(session, story) == []
    sent = prompt_texts(model)
    assert any("Turn 2." in text for text in sent)  # every turn went, verbatim
    reply = (
        await session.scalars(
            select(Message)
            .where(Message.story_id == story.id, Message.role == Role.ASSISTANT)
            .order_by(Message.sequence.desc())
        )
    ).first()
    assert reply is not None
    assert reply.estimated_prompt_tokens is not None
    assert reply.context_audit is not None
    assert "dropped" not in reply.context_audit  # over budget rather than discard…
    assert "/" not in reply.context_audit.split("total")[1]  # …so no budget was applied at all
    assert reply.estimated_prompt_tokens > budget - tune().max_tokens - memory.ROOM_FOR_THE_REPLY
    assert [row.kind for row in await ledger(session, story)] == [SpendKind.REPLY]


async def test_a_reply_too_short_to_be_a_summary_is_refused_rather_than_believed(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.says("##").says("Hm.")

    await send(client, story.id, "I come in.")

    assert await summaries(session, story) == []
    assert any("Turn 2." in text for text in prompt_texts(model))
    kinds = sorted(row.kind for row in await ledger(session, story))
    assert kinds == [SpendKind.REPLY, SpendKind.SUMMARY]  # refused, and still paid for


async def test_a_summary_that_ran_to_the_ceiling_is_kept(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.truncated("A long account of the evening that the ceiling cut off mid" + " word" * 40)
    model.extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    [summary] = await summaries(session, story)
    assert summary.text.startswith("A long account")


async def test_the_summary_is_billed_as_its_own_kind_of_spending(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    rows = {row.kind: row for row in await ledger(session, story)}
    assert sorted(rows) == [SpendKind.FACTS, SpendKind.REPLY, SpendKind.SUMMARY]
    assert rows[SpendKind.SUMMARY].cost is not None
    assert rows[SpendKind.SUMMARY].message_id is None


async def test_the_summariser_is_asked_cold_and_without_a_reasoning_flag(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()), background_model="cheap/model")
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    summary_call = model.calls[0]
    assert summary_call["model"] == "cheap/model"
    assert summary_call["temperature"] == memory.SUMMARY_TEMPERATURE
    assert summary_call["max_tokens"] == memory.SUMMARY_MAX_TOKENS
    assert "reasoning" not in summary_call
    assert model.calls[1]["model"] == "cheap/model"  # the extractor, on the same model
    assert model.calls[2]["model"] == tune().model  # the reply still goes to the story's model


async def test_the_reader_is_named_by_their_persona_rather_than_called_user(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    stretch = model.calls[0]["messages"][1]["content"]
    assert "Rowan Hale: Turn 2." in stretch
    assert "The Gilded Heron: Turn 3." in stretch
    assert "User" not in stretch


async def test_a_question_can_trigger_the_summary_a_turn_would_have(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").extracts().says("It does not say.")

    await send(client, story.id, "/ask how far is the harbour?")

    assert len(await summaries(session, story)) == 1


# --- the batch rules, as pure functions ------------------------------------------------------


def turns(n: int) -> list[Message]:
    return [
        Message(sequence=i + 1, role=Role.USER if i % 2 == 0 else Role.ASSISTANT, text=FILLER)
        for i in range(n)
    ]


def test_nothing_is_compressed_while_everything_fits() -> None:
    assert batch_to_compress(turns(30), allowance=10_000) == []


def test_a_batch_is_at_least_ten_turns_when_that_many_can_be_spared() -> None:
    one_turn = tokens.for_message(FILLER)

    batch = batch_to_compress(turns(30), allowance=one_turn * 28)  # two overflow

    assert len(batch) == memory.WORTH_A_CALL
    assert [t.sequence for t in batch] == list(range(1, 11))


def test_the_newest_six_turns_are_not_compressed_to_widen_a_batch() -> None:
    one_turn = tokens.for_message(FILLER)

    batch = batch_to_compress(turns(12), allowance=one_turn * 11)  # one overflow, 12 turns

    assert len(batch) == 12 - memory.ALWAYS_WHOLE


def test_no_single_summary_is_asked_to_carry_a_whole_backlog() -> None:
    batch = batch_to_compress(turns(200), allowance=0)

    assert len(batch) == memory.AT_MOST_PER_SUMMARY


def test_the_newest_six_turns_are_never_compressed_even_when_the_overflow_reaches_them() -> None:
    """The real playtest of this step summarised the reader's own message (#96)."""
    one_turn = tokens.for_message(FILLER)

    batch = batch_to_compress(turns(20), allowance=one_turn * 3)  # 17 overflow

    assert len(batch) == 20 - memory.ALWAYS_WHOLE


def test_nothing_is_compressed_when_only_the_newest_six_remain() -> None:
    assert batch_to_compress(turns(6), allowance=0) == []
    assert batch_to_compress(turns(4), allowance=0) == []


def test_a_summary_must_account_for_what_it_replaces() -> None:
    source = turns(40)  # about 1,000 tokens

    assert not credible("##", source)
    assert not credible("They talked.", source)
    assert credible("Rowan arrived in the fog. " * 10, source)


async def test_a_stretch_is_compressed_once(session: AsyncSession) -> None:
    story = await a_story(session)
    session.add(
        Summary(story_id=story.id, from_sequence=1, to_sequence=10, text="x", message_count=10)
    )
    await session.flush()
    session.add(
        Summary(story_id=story.id, from_sequence=1, to_sequence=12, text="y", message_count=12)
    )

    with pytest.raises(IntegrityError, match="uq_summaries_story_from"):
        await session.flush()


async def test_a_summary_cannot_end_before_it_starts(session: AsyncSession) -> None:
    story = await a_story(session)
    session.add(
        Summary(story_id=story.id, from_sequence=9, to_sequence=3, text="x", message_count=0)
    )

    with pytest.raises(IntegrityError, match="ck_summaries_range"):
        await session.flush()
