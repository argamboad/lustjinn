"""Every reply carries its audit: what the prompt was built from, estimate beside the bill."""

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import tokens
from lustjinn.context import PERSONA_FRAME
from lustjinn.models import Aside, Message, Role
from scripts.seed_dummy import Dummy
from tests.factories import a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send, stream
from tests.test_turns import a_played_story


async def test_a_stored_reply_says_what_it_was_built_from(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, dummy: Dummy
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    reply = await session.scalar(
        select(Message)
        .where(Message.story_id == story.id, Message.role == Role.ASSISTANT)
        .order_by(Message.sequence.desc())
    )
    assert reply is not None
    card = tokens.for_message(dummy.card)
    persona = tokens.for_message(PERSONA_FRAME + dummy.persona)
    history = tokens.for_message(dummy.opening) + tokens.for_message("I come in.")
    assert reply.context_audit == (
        f"character {card} · persona {persona} · history {history} · "
        f"total {card + persona + history}/32000"
    )
    assert reply.estimated_prompt_tokens == card + persona + history
    assert reply.prompt_tokens == 10  # what the scripted provider reported, kept beside it


async def test_the_estimate_is_the_counters_figure_for_the_prompt_as_sent(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """What the audit stores beside the provider's figure is the counter's own, for exactly the
    messages that went out — no margin, no correction.

    Calibration (#94, 2026-10-08): over the 14 real turns played so far on DeepSeek V4 Flash
    (2,755 to 5,368 prompt tokens) the stored estimate was within 0.2% of the figure OpenRouter
    reported, every time. OpenRouter reports token counts normalised to a GPT vocabulary, which is
    what o200k_base is; the model's native count can differ, and the spend is read from
    `usage.cost`, which the provider works out natively. The "15% high" once recorded here
    compared this fixture's prompt with a real turn's bill — two different prompts."""
    story = await a_played_story(session)
    model.says("Hm.", prompt_tokens=2755)

    await send(
        client,
        story.id,
        "*Rowan steps in out of the fog and shakes the wet from the oilcloth coat.* "
        '"Rowan Hale. A week, perhaps longer. The second part is not complicated — only '
        'unfinished."',
    )

    reply = await session.scalar(
        select(Message)
        .where(Message.story_id == story.id, Message.role == Role.ASSISTANT)
        .order_by(Message.sequence.desc())
    )
    assert reply is not None
    sent = model.calls[-1]["messages"]
    assert reply.estimated_prompt_tokens == sum(tokens.for_message(m["content"]) for m in sent)
    assert reply.prompt_tokens == 2755  # the provider's figure, kept beside it, never mixed in


async def test_a_question_carries_its_audit_too(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("It does not say.")

    await send(client, story.id, "/ask how far is the harbour?")

    aside = await session.scalar(select(Aside).where(Aside.story_id == story.id))
    assert aside is not None
    assert aside.context_audit is not None
    assert aside.context_audit.startswith("character ")
    assert " · instruction " in aside.context_audit
    assert aside.estimated_prompt_tokens is not None


async def test_the_audit_lists_the_newest_replies_first_with_the_rerolled_one_marked_hidden(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("First attempt.").says("Second attempt.")
    await send(client, story.id, "I come in.")
    await stream(client, f"/stories/{story.id}/reroll")

    audit = (await client.get(f"/stories/{story.id}/audit")).json()

    assert [(t["sequence"], t["hidden"]) for t in audit["turns"]] == [
        (4, False),  # the second attempt
        (3, True),  # the first, rerolled away — still here, still worth asking about
        (1, False),  # the opening: a person wrote it, so nothing was built and the audit is empty
    ]
    assert audit["turns"][0]["context"].startswith("character ")
    assert audit["turns"][1]["context"].startswith("character ")
    assert audit["turns"][2]["context"] is None
    assert audit["turns"][0]["prompt_tokens"] == 10
    assert audit["asides"] == []


async def test_the_audit_lists_recent_questions_as_well(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    model.says("No.").says("Yes.")
    await send(client, story.id, "/ask one?")
    await send(client, story.id, "/ask two?")

    audit = (await client.get(f"/stories/{story.id}/audit")).json()

    assert len(audit["asides"]) == 2
    assert all(a["context"].startswith("character ") for a in audit["asides"])


async def test_the_audit_is_the_recent_past_not_the_whole_story(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    for i in range(14):
        model.says(f"Reply {i + 1}.")
        await send(client, story.id, f"Turn {i + 1}.")

    audit = (await client.get(f"/stories/{story.id}/audit")).json()

    assert len(audit["turns"]) == 12
    assert audit["turns"][0]["sequence"] > audit["turns"][-1]["sequence"]


async def test_a_story_that_does_not_exist_or_was_deleted_has_no_audit(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    await session.commit()
    await client.delete(f"/stories/{story.id}")

    assert (await client.get(f"/stories/{story.id}/audit")).status_code == 404
