"""Background calls — summaries, facts — are asked once more, and only when it could help."""

import pytest

from lustjinn.background import once_more_if_worth_it, worth_another_go
from lustjinn.openrouter import ChatMessage, ModelError
from lustjinn.settings import Settings
from tests.scripted_model import ScriptedModel

ASK = [ChatMessage("system", "Summarise."), ChatMessage("user", "Rowan: Hello.")]


@pytest.mark.parametrize("status", [None, 200, 408, 429, 500, 502, 503, 529])
def test_a_failure_a_retry_could_fix_is_worth_another_go(status: int | None) -> None:
    assert worth_another_go(ModelError("…", status))


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413, 422])
def test_a_refusal_is_not_asked_again(status: int) -> None:
    assert not worth_another_go(ModelError("…", status))


async def test_a_host_that_answers_with_nothing_is_asked_once_more(
    model: ScriptedModel, settings: Settings
) -> None:
    model.empty().says("A summary.")
    client = model.client(settings)

    reply = await once_more_if_worth_it(lambda: client.complete(ASK))

    assert reply.text == "A summary."
    assert len(model.calls) == 2


async def test_a_host_that_is_down_is_asked_once_more(
    model: ScriptedModel, settings: Settings
) -> None:
    model.fails("the provider is down", 503).says("A summary.")
    client = model.client(settings)

    reply = await once_more_if_worth_it(lambda: client.complete(ASK))

    assert reply.text == "A summary."
    assert len(model.calls) == 2


async def test_a_rejected_key_is_not_paid_for_twice(
    model: ScriptedModel, settings: Settings
) -> None:
    model.rejected().says("Never reached.")
    client = model.client(settings)

    with pytest.raises(ModelError, match="401"):
        await once_more_if_worth_it(lambda: client.complete(ASK))

    assert len(model.calls) == 1


async def test_two_empty_answers_running_give_up_rather_than_loop(
    model: ScriptedModel, settings: Settings
) -> None:
    model.empty().empty().says("Never reached.")
    client = model.client(settings)

    with pytest.raises(ModelError, match="no message content"):
        await once_more_if_worth_it(lambda: client.complete(ASK))

    assert len(model.calls) == 2
