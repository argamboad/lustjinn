"""Regenerate with a reason: the reason is the only thing that makes the second attempt differ."""

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import regenerate
from lustjinn.regenerate import FRAME, NOTES, Reason, directive
from tests.scripted_model import ScriptedModel
from tests.streaming import Streamed, send, stream
from tests.test_turns import a_played_story, messages


async def reroll(client: httpx2.AsyncClient, story_id: object, **body: object) -> Streamed:
    return await stream(client, f"/stories/{story_id}/reroll", **body)


# --- the directive --------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(Reason))
def test_every_reason_produces_the_frame_and_its_own_note(reason: Reason) -> None:
    text = directive(reason)

    assert text.startswith(FRAME)
    assert text.endswith(NOTES[reason])
    assert reason in regenerate.LABELS
    assert reason in regenerate.DESCRIPTIONS


def test_all_nine_notes_differ() -> None:
    assert len(set(NOTES.values())) == len(Reason) == 9


@pytest.mark.parametrize("reason", list(Reason))
def test_no_directive_speaks_of_the_previous_reply(reason: Reason) -> None:
    """The withdrawn attempt is hidden from the prompt: the model cannot see what it is being
    asked to differ from, so nothing may point at it."""
    assert regenerate.FORBIDDEN not in directive(reason, "and make it rain").lower()


def test_the_readers_words_are_framed_as_a_direction_under_the_note() -> None:
    text = directive(Reason.STEER, "  have her refuse the money  ")

    assert text.endswith(
        NOTES[Reason.STEER] + "\n\nAlso, from the reader: have her refuse the money"
    )
    assert directive(Reason.STEER, "   ") == directive(Reason.STEER)


# --- through the API ------------------------------------------------------------------------------


async def test_a_reroll_sends_its_reason_as_the_last_layer_and_the_old_reply_is_gone(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First version.").says("Second version.")
    await send(client, story.id, "Hello.")

    streamed = await reroll(client, story.id, reason="looping")

    assert streamed.done["reply"]["text"] == "Second version."
    sent = model.last["messages"]
    assert sent[-1] == {"role": "system", "content": directive(Reason.LOOPING)}
    assert sent[-2] == {"role": "user", "content": "Hello."}
    assert all("First version." not in m["content"] for m in sent)
    visible = [m.text for m in await messages(session, story)]
    assert visible[1:] == ["Hello.", "Second version."]


async def test_the_typed_guidance_is_a_direction_never_the_latest_message(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First version.").says("Second version.")
    await send(client, story.id, "Hello.")

    await reroll(client, story.id, reason="steer", instructions="have her refuse the money")

    sent = model.last["messages"]
    assert sent[-1]["content"].endswith("Also, from the reader: have her refuse the money")
    assert sent[-1]["role"] == "system"
    assert [m["content"] for m in sent if m["role"] == "user"] == ["Hello."]
    stored = await messages(session, story, hidden=True)
    assert not any("refuse the money" in m.text for m in stored)


async def test_a_bare_reroll_still_asks_for_the_turn_afresh(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First version.").says("Second version.")
    await send(client, story.id, "Hello.")

    await reroll(client, story.id)

    assert model.last["messages"][-1]["content"] == directive(Reason.NONE)


async def test_an_unknown_reason_is_refused_before_anything_is_hidden(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First version.")
    await send(client, story.id, "Hello.")

    streamed = await reroll(client, story.id, reason="because")

    assert streamed.status == 422
    visible = [m.text for m in await messages(session, story)]
    assert visible[1:] == ["Hello.", "First version."]
    assert len(model.calls) == 1
