"""Facts: what is true now, extracted after each summary, with the turns it held for."""

import json
from collections.abc import Callable

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import facts
from lustjinn.context import WORLD_FRAME
from lustjinn.models import Fact, SpendKind, Story
from lustjinn.settings import Settings
from scripts.seed_dummy import Dummy
from tests.factories import a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_summaries import a_budget_that_holds, a_long_story
from tests.test_turns import ledger


async def all_facts(session: AsyncSession, story: Story) -> list[Fact]:
    rows = await session.scalars(
        select(Fact)
        .where(Fact.story_id == story.id)
        .order_by(Fact.valid_from_sequence, Fact.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows)


def world_sent(model: ScriptedModel) -> str | None:
    return next(
        (m["content"] for m in model.last["messages"] if m["content"].startswith(WORLD_FRAME)),
        None,
    )


def tight(tune: Callable[..., Settings], dummy: Dummy) -> None:
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))


async def test_facts_are_extracted_from_the_summarised_stretch_and_reach_the_same_turn(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    model.summarises("Rowan took room seven.")
    model.extracts([("Rowan Hale", "has room seven."), ("Isaure", "noticed the satchel.")])
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    stored = await all_facts(session, story)
    assert [(f.subject, f.text) for f in stored] == [
        ("Rowan Hale", "has room seven."),
        ("Isaure", "noticed the satchel."),
    ]
    assert all(f.valid_from_sequence == 1 for f in stored)  # where the stretch began
    assert all(f.valid_to_sequence is None and not f.pinned for f in stored)
    assert all(f.model == "test-model" for f in stored)
    assert world_sent(model) == (
        WORLD_FRAME + "Rowan Hale: has room seven.\nIsaure: noticed the satchel."
    )


async def test_the_extractor_sees_the_existing_facts_and_the_new_stretch(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    session.add(facts.add(story, "Blake", "sits where he can see the door.", 1, model="m"))
    await session.commit()
    model.summarises("Stretch.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    asked = model.calls[1]
    assert asked["messages"][0]["content"] == facts.INSTRUCTION
    body = asked["messages"][1]["content"]
    assert "Existing facts:\n" in body
    assert "| Blake | sits where he can see the door." in body
    assert "New transcript:\nThe Gilded Heron: " in body  # the stretch begins with the opening
    assert "Rowan Hale: Turn 2." in body
    assert asked["temperature"] == facts.FACTS_TEMPERATURE
    assert asked["max_tokens"] == facts.FACTS_MAX_TOKENS
    assert "reasoning" not in asked


async def test_a_retired_fact_leaves_the_next_prompt_and_keeps_its_range(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    old = facts.add(story, "Isaure", "distrusts Rowan.", 1, model="m")
    session.add(old)
    await session.commit()
    model.summarises("Stretch.").extracts([("Isaure", "trusts Rowan.")], [old.id.hex[:8]])
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    retired, new = await all_facts(session, story)
    assert retired.id == old.id
    assert retired.valid_to_sequence is not None  # the end of the stretch that contradicted it
    assert new.text == "trusts Rowan."
    assert world_sent(model) == WORLD_FRAME + "Isaure: trusts Rowan."


async def test_the_model_cannot_retire_a_fact_a_person_stated(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    pinned = facts.add(story, "Rowan Hale", "is allergic to shellfish.", 1)  # no model: a person
    session.add(pinned)
    await session.commit()
    model.summarises("Stretch.").extracts([], [pinned.id.hex[:8]]).says("Hm.")

    await send(client, story.id, "I come in.")

    [still] = await all_facts(session, story)
    assert still.pinned
    assert still.valid_to_sequence is None
    assert world_sent(model) == WORLD_FRAME + "Rowan Hale: is allergic to shellfish."


async def test_an_ambiguous_or_unknown_id_retires_nothing(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    one = facts.add(story, "A", "one.", 1, model="m")
    two = facts.add(story, "B", "two.", 1, model="m")
    session.add_all([one, two])
    await session.commit()
    shared = ""  # the empty prefix matches both
    model.summarises("Stretch.").extracts([], [shared, "zzzzzzzz"]).says("Hm.")

    await send(client, story.id, "I come in.")

    assert all(f.valid_to_sequence is None for f in await all_facts(session, story))


async def test_json_wrapped_in_a_code_fence_is_still_read(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").extracts([("Mags", "owes nobody.")], fenced=True).says("Hm.")

    await send(client, story.id, "I come in.")

    assert [f.text for f in await all_facts(session, story)] == ["owes nobody."]


async def test_an_answer_that_is_not_json_records_nothing_and_is_still_billed(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").says("I would rather not.").says("Hm.")

    streamed = await send(client, story.id, "I come in.")

    assert streamed.done["reply"]["text"] == "Hm."
    assert await all_facts(session, story) == []
    kinds = sorted(row.kind for row in await ledger(session, story))
    assert kinds == [SpendKind.FACTS, SpendKind.REPLY, SpendKind.SUMMARY]


async def test_an_extractor_that_fails_does_not_cost_the_reader_the_reply_or_the_summary(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    tight(tune, dummy)
    story = await a_long_story(session, 30)
    model.summarises("Stretch.").fails().fails().says("Hm.")

    streamed = await send(client, story.id, "I come in.")

    assert streamed.done["reply"]["text"] == "Hm."
    assert await all_facts(session, story) == []
    kinds = sorted(row.kind for row in await ledger(session, story))
    assert kinds == [SpendKind.REPLY, SpendKind.SUMMARY]  # the failed calls bill nothing
    assert any(
        text.startswith("Stretch.") for text in [m["content"] for m in model.last["messages"]]
    )


async def test_a_story_that_fits_extracts_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_long_story(session, 6)
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    assert await all_facts(session, story) == []
    assert world_sent(model) is None


# --- the pure parts ---------------------------------------------------------------------------


def test_the_answer_is_read_from_the_first_brace_to_the_last() -> None:
    document = '{"facts": [{"subject": "A", "text": "b."}], "retired": ["ab12"]}'
    answer = f"Here you go:\n```json\n{document}\n```\nDone."

    found, retired = facts.parse(answer)

    assert found == [("A", "b.")]
    assert retired == ["ab12"]


def test_entries_that_are_not_the_agreed_shape_are_skipped() -> None:
    answer = json.dumps(
        {
            "facts": [{"subject": "A", "text": "b."}, "junk", {"subject": "", "text": "x"}],
            "retired": [7, " c3 "],
        }
    )

    found, retired = facts.parse(answer)

    assert found == [("A", "b.")]
    assert retired == ["c3"]


def test_an_answer_with_no_object_in_it_is_refused() -> None:
    with pytest.raises(ValueError, match="no JSON object"):
        facts.parse("I would rather not.")


def test_the_instruction_forbids_the_user_as_a_subject() -> None:
    assert 'Never "User", "the user" or "the reader"' in facts.INSTRUCTION


async def test_a_fact_cannot_end_before_it_began(session: AsyncSession) -> None:
    story = await a_story(session)
    fact = facts.add(story, "A", "b.", 10, model="m")
    fact.valid_to_sequence = 3
    session.add(fact)

    with pytest.raises(IntegrityError, match="ck_facts_range"):
        await session.flush()
