"""Fallback: when a story's own model cannot take the turn, the default writes it and says so."""

from collections.abc import Callable

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Story
from lustjinn.settings import Settings
from scripts.seed_dummy import Dummy
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_summaries import a_budget_that_holds, a_long_story
from tests.test_turns import a_played_story, ledger, messages


async def on_a_model(session: AsyncSession, story: Story, model: str, context: int | None) -> None:
    """Puts the story on a model as if it had been checked and saved with that window."""
    story.model = model
    story.model_context = context
    await session.commit()


async def test_a_prompt_larger_than_the_story_models_room_is_written_by_the_default(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    # A window that leaves less room than the card alone needs, once the reply's ceiling is out.
    await on_a_model(session, story, "small/model", settings.max_tokens + 2_100)
    model.says("Hm.")

    streamed = await send(client, story.id, "I come in.")

    assert len(model.calls) == 1  # decided before anything was sent
    assert model.last["model"] == settings.model
    reply = streamed.done["reply"]
    assert reply["fell_back_from"] == "small/model"
    assert (await messages(session, story))[-1].fell_back_from == "small/model"
    assert (await reloaded(session, story)).model == "small/model"  # the story keeps its model


async def test_a_model_with_no_host_hands_the_turn_to_the_default(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    await on_a_model(session, story, "gone/model", 128_000)
    model.has_no_such_model().says("Hm.")

    streamed = await send(client, story.id, "I come in.")

    first, second = model.calls
    assert (first["model"], second["model"]) == ("gone/model", settings.model)
    assert streamed.text == "Hm."
    assert streamed.done["reply"]["fell_back_from"] == "gone/model"
    [row] = await ledger(session, story)  # the refused call billed nothing
    assert row.model == "test-model"


async def test_the_fallback_is_in_the_story_the_clients_read(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await on_a_model(session, story, "gone/model", 128_000)
    model.has_no_such_model().says("Hm.").says("Again.")
    await send(client, story.id, "I come in.")
    await send(client, story.id, "Hello?")  # not scripted to fail: no second fallback

    read = (await client.get(f"/stories/{story.id}")).json()

    assert [m["fell_back_from"] for m in read["messages"]] == [None, None, "gone/model", None, None]


async def test_anything_but_a_missing_model_is_reported_not_retried(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await on_a_model(session, story, "some/model", 128_000)
    model.rejected()

    streamed = await send(client, story.id, "I come in.")

    assert streamed.last[0] == "error"
    assert len(model.calls) == 1
    assert len(await messages(session, story)) == 2  # the opening and the kept message


async def test_a_story_on_the_default_has_nothing_to_fall_back_to(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.has_no_such_model()

    streamed = await send(client, story.id, "I come in.")

    assert streamed.last[0] == "error"
    assert len(model.calls) == 1


async def test_the_default_writes_at_its_own_temperature_not_the_story_models(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """Creativity's 1.4 is 0.9 on a finetune with a measured range; the default takes 1.4."""
    story = await a_played_story(session)
    await on_a_model(session, story, "thedrummer/cydonia-24b-v4.1", 128_000)
    await client.put(f"/stories/{story.id}/dials/creativity", json={"value": "4"})
    model.has_no_such_model().says("Hm.")

    await send(client, story.id, "I come in.")

    first, second = model.calls
    assert (first["temperature"], second["temperature"]) == (0.9, 1.4)


async def test_the_memory_stays_on_the_default_whatever_the_story_plays_on(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
    settings: Settings,
) -> None:
    """Every story's memory is written alike."""
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    await on_a_model(session, story, "some/model", 128_000)
    model.summarises("Stretch.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    summary, extraction, reply = model.calls
    assert summary["model"] == settings.model
    assert extraction["model"] == settings.model
    assert reply["model"] == "some/model"


async def reloaded(session: AsyncSession, story: Story) -> Story:
    await session.refresh(story)
    return story
