"""Snippets expand at send time, and only where a trigger genuinely opens a word."""

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.snippets import by_name, expand
from tests.factories import a_character, a_snippet, a_story
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_turns import messages

STORM = by_name({"storm": "Rain hammers the glass.", "Long-Night": "The night goes on."})


def test_a_trigger_that_opens_a_word_is_replaced_by_the_snippet() -> None:
    assert (
        expand(":storm and then she speaks", STORM) == "Rain hammers the glass. and then she speaks"
    )
    assert expand("She waits. :storm", STORM) == "She waits. Rain hammers the glass."
    assert expand("line one\n:storm", STORM) == "line one\nRain hammers the glass."


def test_the_name_is_matched_without_regard_to_case() -> None:
    assert expand(":STORM", STORM) == "Rain hammers the glass."
    assert expand(":long-night", STORM) == "The night goes on."


def test_clock_times_urls_and_colons_in_prose_are_left_as_typed() -> None:
    text = "at 10:30, see https://x.test and note: this"

    assert expand(text, STORM) == text


def test_an_unknown_name_is_left_as_typed() -> None:
    assert expand(":nothing happened", STORM) == ":nothing happened"
    assert expand(":", STORM) == ":"
    assert expand(": storm", STORM) == ": storm"


def test_a_closed_shortcode_is_an_emoji_for_the_clients_and_passes_through() -> None:
    assert expand(":storm: here", STORM) == ":storm: here"
    assert expand(":fire: and :storm", STORM) == ":fire: and Rain hammers the glass."


def test_a_trigger_must_open_a_word() -> None:
    assert expand("a:storm", STORM) == "a:storm"
    assert expand("the ratio 1:storm", STORM) == "the ratio 1:storm"


def test_a_name_ends_at_the_first_character_that_cannot_be_in_one() -> None:
    assert expand(":storm, she said", STORM) == "Rain hammers the glass., she said"
    assert expand(":storm.", STORM) == "Rain hammers the glass.."


def test_a_name_too_long_to_be_one_is_not_looked_up() -> None:
    long = ":" + "s" * 40
    calls: list[str] = []

    def spy(name: str) -> str | None:
        calls.append(name)
        return None

    assert expand(long, spy) == long
    assert calls == []


def test_an_expansion_is_not_scanned_again() -> None:
    """A snippet whose text mentions another trigger does not expand it: one pass, as typed."""
    nested = by_name({"a": ":b", "b": "B!"})

    assert expand(":a", nested) == ":b"


async def test_a_message_with_a_trigger_is_stored_expanded(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    await a_snippet(session, "storm", "Rain hammers the glass.")
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("She looks up.")

    streamed = await send(client, story.id, "I come in. :storm")

    assert streamed.done["sent"]["text"] == "I come in. Rain hammers the glass."
    sent, _ = await messages(session, story)
    assert sent.text == "I come in. Rain hammers the glass."
    assert model.last["messages"][-1]["content"] == "I come in. Rain hammers the glass."


async def test_a_trigger_nobody_wrote_a_snippet_for_is_sent_as_typed(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("Hm.")

    streamed = await send(client, story.id, "At 10:30 :nothing happens")

    assert streamed.done["sent"]["text"] == "At 10:30 :nothing happens"


async def test_a_retry_hashes_the_expanded_text_so_it_is_still_one_turn(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    await a_snippet(session, "storm", "Rain hammers the glass.")
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.fails().says("She looks up.")

    await send(client, story.id, ":storm")
    second = await send(client, story.id, ":storm")

    assert second.done["sent"]["text"] == "Rain hammers the glass."
    assert len(await messages(session, story)) == 2


async def test_a_snippet_expands_in_a_question_too(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """Expansion happens before the line is read for commands, as the donor does it."""
    await a_snippet(session, "her", "the keeper of the light")
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("Nothing says.")

    streamed = await send(client, story.id, "/ask Who is :her ?")

    assert streamed.done["aside"]["question"] == "Who is the keeper of the light ?"


async def test_an_expanded_message_is_what_a_later_edit_of_the_snippet_cannot_reach(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    """Copied when used, never read again: the message says what the snippet said that day."""
    snippet = await a_snippet(session, "storm", "Rain hammers the glass.")
    story = await a_story(session, await a_character(session))
    await session.commit()
    model.says("Hm.")
    await send(client, story.id, ":storm")

    snippet.text = "Hail now."
    await session.commit()

    sent, _ = await messages(session, story)
    assert sent.text == "Rain hammers the glass."
