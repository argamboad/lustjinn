"""A model per story: checked before it is saved, fitted to its window, changeable at any turn."""

from collections.abc import Callable
from decimal import Decimal

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import openrouter, story_model, tokens
from lustjinn.models import Story
from lustjinn.settings import Settings
from scripts.seed_dummy import Dummy
from tests.scripted_model import ScriptedModel, a_listed_model
from tests.streaming import send
from tests.test_turns import a_played_story, messages

SMALL = "small/model"
"""A model whose listed window holds the dummy's card and little else."""


def a_small_window(dummy: Dummy, settings: Settings) -> int:
    fixed = tokens.for_message(dummy.card) + tokens.for_message(dummy.persona) + 40
    return fixed + settings.max_tokens + story_model.ROOM_FOR_A_TURN + 500


async def set_model(client: httpx2.AsyncClient, story_id: object, model: str | None):
    return await client.put(f"/stories/{story_id}/model", json={"model": model})


async def reloaded(session: AsyncSession, story: Story) -> Story:
    await session.refresh(story)
    return story


# --- the list ------------------------------------------------------------------------------------


async def test_the_choices_are_listed_with_prices_and_how_each_compares_with_the_default(
    client: httpx2.AsyncClient, model: ScriptedModel, settings: Settings
) -> None:
    model.lists(
        a_listed_model("thedrummer/cydonia-24b-v4.1", 131_072, "0.00000028", "0.00000056"),
        a_listed_model(
            "cognitivecomputations/dolphin-mistral-24b-venice-edition",
            131_072,
            "0.00000007",
            "0.00000014",
        ),
    )

    response = await client.get("/models")

    assert response.status_code == 200
    listed = {c["id"]: c for c in response.json()}
    assert response.json()[0]["id"] == settings.model  # the default first
    assert listed[settings.model]["is_default"] is True
    assert Decimal(listed[settings.model]["prompt_per_million"]) == Decimal("0.14")
    cydonia = listed["thedrummer/cydonia-24b-v4.1"]
    assert cydonia["listed"] is True
    assert Decimal(cydonia["prompt_price_ratio"]) == Decimal("2.00")
    assert cydonia["context_length"] == 131_072
    dolphin = listed["cognitivecomputations/dolphin-mistral-24b-venice-edition"]
    assert dolphin["context_length"] == 32_768  # the shipped correction, believed over the list
    assert Decimal(dolphin["prompt_price_ratio"]) == Decimal("0.50")
    unlisted = listed["z-ai/glm-4.6"]
    assert unlisted["listed"] is False
    assert unlisted["prompt_per_million"] is None
    assert len(response.json()) == 1 + len(settings.model_choices)


async def test_the_list_is_read_once_and_kept_for_ten_minutes(
    client: httpx2.AsyncClient, model: ScriptedModel
) -> None:
    await client.get("/models")
    await client.get("/models")

    assert sum(1 for r in model.requests if r.url.path.endswith("/models")) == 1


async def test_a_list_that_cannot_be_read_is_a_503(
    client: httpx2.AsyncClient, model: ScriptedModel
) -> None:
    model.catalogue_down = True

    response = await client.get("/models")

    assert response.status_code == 503


# --- setting a story's model --------------------------------------------------------------------


async def test_a_listed_model_is_saved_and_the_next_turn_uses_it(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    model.lists(a_listed_model("some/model", 64_000, "0.000001", "0.000002")).says("Hm.")

    before = (await client.get(f"/stories/{story.id}/model")).json()
    changed = await set_model(client, story.id, "SOME/model")
    await send(client, story.id, "I come in.")

    assert before == {"model": None, "context": None, "default": settings.model, "message": None}
    assert changed.status_code == 200
    assert changed.json() == {
        "model": "some/model",  # as the provider spells it
        "context": 64_000,
        "default": settings.model,
        "message": "This story now uses some/model.",
    }
    assert model.last["model"] == "some/model"
    assert (await messages(session, story))[-1].model == "test-model"  # what the API reported


async def test_a_model_the_provider_does_not_list_is_refused_and_the_story_keeps_its_own(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.lists(a_listed_model("some/model", 64_000, "0.000001", "0.000002"))
    await set_model(client, story.id, "some/model")

    refused = await set_model(client, story.id, "no/such")

    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "no/such is not available — the provider does not list it — so it was not set. The "
        "story stays on some/model."
    )
    assert (await reloaded(session, story)).model == "some/model"


async def test_a_model_that_cannot_be_checked_is_not_set(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    model.catalogue_down = True

    refused = await set_model(client, story.id, "some/model")

    assert refused.status_code == 503
    assert "could not be checked" in refused.json()["detail"]
    assert refused.json()["detail"].endswith(f"The story stays on {settings.model}.")
    assert (await reloaded(session, story)).model is None


async def test_a_model_that_cannot_hold_the_character_and_a_reply_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, dummy: Dummy
) -> None:
    story = await a_played_story(session)
    model.lists(a_listed_model("tiny/model", 2_048, "0.000001", "0.000002"))

    refused = await set_model(client, story.id, "tiny/model")

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail.startswith("tiny/model can read 2,048 tokens, and this story needs ")
    assert "for the character, persona and dials" in detail
    assert "It cannot be played on it, so it was not set." in detail
    assert (await reloaded(session, story)).model is None


async def test_the_response_length_dial_counts_against_the_window(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    dummy: Dummy,
    settings: Settings,
) -> None:
    story = await a_played_story(session)
    window = a_small_window(dummy, settings)
    model.lists(a_listed_model(SMALL, window, "0.000001", "0.000002"))

    fits = await set_model(client, story.id, SMALL)
    await client.put(f"/stories/{story.id}/dials/response-length", json={"value": "4"})  # 2,600
    await set_model(client, story.id, None)
    no_longer = await set_model(client, story.id, SMALL)

    assert fits.status_code == 200
    assert no_longer.status_code == 422
    assert "2,600 for the reply" in no_longer.json()["detail"]


async def test_the_budget_shrinks_to_a_small_window_and_the_message_says_so(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    dummy: Dummy,
    settings: Settings,
) -> None:
    story = await a_played_story(session)
    window = a_small_window(dummy, settings)
    model.lists(a_listed_model(SMALL, window, "0.000001", "0.000002")).says("Hm.")

    changed = await set_model(client, story.id, SMALL)
    await send(client, story.id, "I come in.")

    assert changed.json()["message"] == (
        f"This story now uses {SMALL}. It can read {window:,} tokens, under the "
        f"{settings.context_budget:,} budget, so the story's budget shrinks to fit it and "
        "older turns compress sooner."
    )
    fitted = story_model.fitted(settings, await reloaded(session, story))
    assert fitted.context_budget == window - settings.max_tokens
    audit = (await client.get(f"/stories/{story.id}/audit")).json()
    assert audit["turns"][0]["context"].endswith(f"/{fitted.context_budget}")


def test_the_budget_never_shrinks_below_the_floor(settings: Settings) -> None:
    story = Story(name="x", model="tiny/model", model_context=settings.max_tokens + 100)

    assert story_model.fitted(settings, story).context_budget == story_model.LEAST_BUDGET
    assert story_model.fitted(settings, Story(name="y")) is settings
    assert (
        story_model.fitted(settings, Story(name="z", model="big/model", model_context=None))
        is settings
    )


async def test_the_default_or_null_returns_the_story_to_the_default(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    model.lists(a_listed_model("some/model", 64_000, "0.000001", "0.000002"))
    await set_model(client, story.id, "some/model")

    by_name = await set_model(client, story.id, settings.model.upper())
    assert (await reloaded(session, story)).model is None
    await set_model(client, story.id, "some/model")
    by_null = await set_model(client, story.id, None)

    assert by_name.json()["message"] == f"This story uses the default, {settings.model}."
    assert by_null.json() == {
        "model": None,
        "context": None,
        "default": settings.model,
        "message": f"This story uses the default, {settings.model}.",
    }
    assert sum(1 for r in model.requests if r.url.path.endswith("/models")) == 1  # cached


def test_a_window_is_a_correction_first_then_the_list(
    settings: Settings, tune: Callable[..., Settings]
) -> None:
    dolphin = "cognitivecomputations/dolphin-mistral-24b-venice-edition"

    assert openrouter.window_of(settings, dolphin, 131_072) == 32_768
    assert openrouter.window_of(settings, dolphin, 16_000) == 16_000  # never above the list
    assert openrouter.window_of(settings, dolphin, None) == 32_768
    assert openrouter.window_of(settings, "other/model", 64_000) == 64_000
    assert openrouter.window_of(settings, "other/model", None) is None
    configured = tune(model_windows={"Other/Model": 8_000})
    assert openrouter.window_of(configured, "other/model", 64_000) == 8_000


async def test_a_story_needs_to_exist(client: httpx2.AsyncClient) -> None:
    missing = "01a10d31-0000-7000-8000-000000000000"

    assert (await client.get(f"/stories/{missing}/model")).status_code == 404
    assert (await set_model(client, missing, None)).status_code == 404
