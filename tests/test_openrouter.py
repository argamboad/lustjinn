"""The OpenRouter client: what it sends, how it reads a stream back, and how it fails."""

from decimal import Decimal

import pytest
from pydantic import SecretStr

from lustjinn.openrouter import ChatMessage, ModelError, OpenRouter, Reply, temperature_for
from lustjinn.settings import Settings
from tests.scripted_model import ScriptedModel

HELLO = [ChatMessage("system", "You are Elena."), ChatMessage("user", "Hello.")]


def configured(settings: Settings, **changes: object) -> Settings:
    return settings.model_copy(update=changes)


async def test_the_reply_arrives_in_pieces_and_then_whole(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("I could say the same about you.")

    pieces: list[str | Reply] = [p async for p in model.client(settings).stream(HELLO)]

    *text, reply = pieces
    assert "".join(p for p in text if isinstance(p, str)) == "I could say the same about you."
    assert len(text) == 2  # streamed, not delivered in one go
    assert isinstance(reply, Reply)
    assert reply.text == "I could say the same about you."


async def test_the_reply_carries_the_usage_the_cost_and_the_host(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("She looks up.")

    reply = await model.client(settings).complete(HELLO)

    assert reply.model == "test-model"
    assert reply.provider == "test-host"
    assert reply.generation_id == "gen-1"
    assert (reply.prompt_tokens, reply.completion_tokens, reply.cached_tokens) == (10, 5, 4)
    assert reply.cost == Decimal("0.0002")
    assert isinstance(reply.cost, Decimal)  # money is never a float
    assert reply.finish_reason == "stop"
    assert not reply.truncated


async def test_a_call_the_api_did_not_price_has_no_cost_rather_than_zero(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says_unpriced("She looks up.")

    reply = await model.client(settings).complete(HELLO)

    assert reply.cost is None
    assert reply.provider is None
    assert reply.prompt_tokens == 10


async def test_a_reply_stopped_at_the_ceiling_is_reported_as_truncated(
    model: ScriptedModel, settings: Settings
) -> None:
    model.truncated("It went on and")

    reply = await model.client(settings).complete(HELLO)

    assert reply.truncated


async def test_the_request_asks_for_a_stream_of_the_configured_model(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("Hm.")

    await model.client(settings).complete(HELLO)

    sent = model.last
    assert sent["model"] == "deepseek/deepseek-v4-flash"
    assert sent["stream"] is True
    assert sent["temperature"] == 1.0
    assert sent["max_tokens"] == 1024
    assert sent["messages"] == [
        {"role": "system", "content": "You are Elena."},
        {"role": "user", "content": "Hello."},
    ]


async def test_the_key_travels_as_a_bearer_token_with_the_attribution_headers(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("Hm.")

    await model.client(settings).complete(HELLO)

    request = model.requests[-1]
    assert request.headers["Authorization"] == "Bearer sk-or-test"
    assert request.headers["HTTP-Referer"] == "https://github.com/argamboad/lustjinn"
    assert request.headers["X-Title"] == "Lustjinn"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"


async def test_the_base_url_is_honoured_and_not_double_slashed(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("Hm.")

    await model.client(
        configured(settings, openrouter_base_url="https://example.test/v1/")
    ).complete(HELLO)

    assert str(model.requests[-1].url) == "https://example.test/v1/chat/completions"


async def test_an_explicit_model_and_sampling_override_the_configured_ones(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("Hm.")

    await model.client(settings).complete(
        HELLO, model="deepseek/deepseek-v4-pro", temperature=0.4, max_tokens=600
    )

    assert model.last["model"] == "deepseek/deepseek-v4-pro"
    assert model.last["temperature"] == 0.4
    assert model.last["max_tokens"] == 600


async def test_reasoning_and_the_penalty_are_sent_only_when_asked(
    model: ScriptedModel, settings: Settings
) -> None:
    """Absent and zero are different requests to some backends; only absent means no opinion."""
    model.says("Hm.").says("Hm.")
    client = model.client(settings)

    await client.complete(HELLO)
    assert "reasoning" not in model.last
    assert "frequency_penalty" not in model.last

    await client.complete(HELLO, reasoning=False, frequency_penalty=0.0)
    assert model.last["reasoning"] == {"enabled": False}
    assert model.last["frequency_penalty"] == 0.0


async def test_provider_routing_is_omitted_unless_something_is_configured(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("Hm.").says("Hm.")

    await model.client(settings).complete(HELLO)
    assert "provider" not in model.last

    routed = configured(
        settings,
        prefer_providers=[" DeepInfra ", "novita", ""],
        ignore_providers=["chutes"],
        allow_provider_fallbacks=False,
    )
    await model.client(routed).complete(HELLO)
    # Trimmed, never lower-cased: a slug the router does not know is dropped silently, so
    # mangling the case to be helpful would only hide the typo.
    assert model.last["provider"] == {
        "order": ["DeepInfra", "novita"],
        "ignore": ["chutes"],
        "allow_fallbacks": False,
    }


async def test_a_missing_key_fails_before_anything_is_sent(
    model: ScriptedModel, settings: Settings
) -> None:
    model.says("Hm.")

    with pytest.raises(ModelError, match="LUSTJINN_OPENROUTER_API_KEY") as refused:
        await model.client(configured(settings, openrouter_api_key=None)).complete(HELLO)

    assert refused.value.status == 401
    assert model.requests == []


async def test_an_empty_conversation_is_refused_without_a_call(
    model: ScriptedModel, settings: Settings
) -> None:
    with pytest.raises(ValueError, match="at least one message"):
        await model.client(settings).complete([])

    assert model.requests == []


async def test_a_refusal_carries_the_status_and_the_apis_message_but_not_its_body(
    model: ScriptedModel, settings: Settings
) -> None:
    model.fails("Insufficient credits", 402)

    with pytest.raises(ModelError) as refused:
        await model.client(settings).complete(HELLO)

    assert refused.value.status == 402
    assert "402" in str(refused.value)
    assert "Insufficient credits" in str(refused.value)
    assert "{" not in str(refused.value)  # the message, not the JSON around it


@pytest.mark.parametrize(
    ("status", "message", "no_such_model"),
    [
        (404, "No endpoints found for x/y.", True),
        (400, "x/y is not a valid model ID", True),
        (400, "max_tokens is too large", False),
        (401, "No auth credentials found", False),
        (402, "Insufficient credits", False),
    ],
)
async def test_only_a_refusal_about_the_model_itself_says_there_is_no_such_model(
    model: ScriptedModel, settings: Settings, status: int, message: str, no_such_model: bool
) -> None:
    model.fails(message, status)

    with pytest.raises(ModelError) as refused:
        await model.client(settings).complete(HELLO)

    assert refused.value.no_such_model is no_such_model


async def test_a_success_with_no_content_is_a_failure_that_says_why(
    model: ScriptedModel, settings: Settings
) -> None:
    """An empty string stored as a reply would be a turn that never happened."""
    model.empty()

    with pytest.raises(ModelError) as refused:
        await model.client(settings).complete(HELLO)

    assert refused.value.status == 200
    assert "finish_reason: stop" in str(refused.value)
    assert "served by test-host" in str(refused.value)


async def test_a_model_that_only_reasoned_is_named_as_such(
    model: ScriptedModel, settings: Settings
) -> None:
    model.reasons_only()

    with pytest.raises(ModelError, match="reasoning only"):
        await model.client(settings).complete(HELLO)


async def test_an_error_mid_stream_is_a_failure_not_a_short_reply(
    model: ScriptedModel, settings: Settings
) -> None:
    model.breaks_mid_stream("Provider returned error")

    with pytest.raises(ModelError, match=r"mid-stream.*Provider returned error") as refused:
        await model.client(settings).complete(HELLO)

    assert refused.value.status == 502


async def test_a_body_that_is_not_a_stream_is_reported_as_such(
    model: ScriptedModel, settings: Settings
) -> None:
    """A gateway's HTML page, say — not "no content", which would point at the wrong problem."""
    model.not_json()

    with pytest.raises(ModelError, match="not a stream"):
        await model.client(settings).complete(HELLO)


async def test_listing_models_gives_the_window_and_the_price_per_million(
    model: ScriptedModel, settings: Settings
) -> None:
    import httpx2

    listing = {
        "data": [
            {
                "id": "deepseek/deepseek-v4-flash",
                "context_length": 1048576,
                "pricing": {"prompt": "0.00000008", "completion": "0.00000016"},
            },
            {"id": "local/plain"},
            {"no": "id"},
        ]
    }
    client = OpenRouter(
        settings,
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=listing))
        ),
    )

    [flash, plain] = await client.models()

    assert (flash.id, flash.context_length) == ("deepseek/deepseek-v4-flash", 1048576)
    assert (flash.prompt_per_million, flash.completion_per_million) == (
        Decimal("0.08"),
        Decimal("0.16"),
    )
    assert (plain.context_length, plain.prompt_per_million) == (None, None)


def test_a_model_with_a_measured_range_gets_the_dials_temperature_mapped_onto_it() -> None:
    dolphin = "cognitivecomputations/dolphin-mistral-24b-venice-edition"

    assert temperature_for(dolphin, 0.6) == 0.3  # the dial's bottom is the model's bottom
    assert temperature_for(dolphin, 1.4) == 0.9  # and its top is the model's top
    assert temperature_for(dolphin, 1.0) == 0.6
    assert temperature_for(dolphin, 0.4) == 0.15  # colder than the dial lands proportionally
    assert temperature_for(dolphin, 0.0) == 0.05  # never below a floor that still samples
    assert temperature_for(dolphin.upper(), 1.0) == 0.6


def test_a_model_with_no_measured_range_keeps_the_temperature_asked() -> None:
    assert temperature_for("deepseek/deepseek-v4-flash", 1.3) == 1.3


def test_the_settings_know_the_defaults(settings: Settings) -> None:
    assert settings.model == "deepseek/deepseek-v4-flash"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert (settings.temperature, settings.max_tokens, settings.model_timeout_seconds) == (
        1.0,
        1024,
        180,
    )
    assert settings.think_before_replying is False
    assert settings.openrouter_api_key == SecretStr("sk-or-test")
