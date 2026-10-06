"""Meters: the model draws them at the end of each reply, and the app reads the values back."""

from collections.abc import Callable

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import trackers
from lustjinn.models import Story, Tracker
from lustjinn.settings import Settings
from lustjinn.trackers import HEADER, MOVEMENT, SHAPE, absorb, bar, render, split_command
from scripts.seed_dummy import Dummy
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_summaries import a_budget_that_holds, a_long_story
from tests.test_turns import a_played_story, ledger, messages


def a_tracker(
    name: str = "Trust", value: float = 40, maximum: float = 100, **words: str
) -> Tracker:
    return Tracker(name=name, value=value, max=maximum, delta=0, **words)


async def stored(session: AsyncSession, story: Story) -> list[Tracker]:
    rows = await session.scalars(
        select(Tracker)
        .where(Tracker.story_id == story.id)
        .order_by(Tracker.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- rendering ------------------------------------------------------------------------------------


def test_no_meters_render_nothing() -> None:
    assert render([]) is None


def test_the_prompt_carries_the_shape_the_rules_and_each_meter_where_it_stands() -> None:
    trust = a_tracker(means="how far she trusts Rowan", anchors="0 a stranger, 100 family")
    trust.delta = 3
    trust.note = "the first honest answer"
    heat = a_tracker("Heat", 2.5, 10, rule="never more than 1 in a turn")

    rendered = render([trust, heat])

    assert rendered == (
        f"{HEADER}\n\n{SHAPE}\n\n{MOVEMENT}\n\n"
        "[Trust] ####...... 40/100 | Δ +3 | the first honest answer\n"
        "    measures: how far she trusts Rowan\n"
        "    scale: 0 a stranger, 100 family\n"
        "[Heat] ##........ 2.5/10 | Δ 0 | —\n"
        "    rule: never more than 1 in a turn"
    )


def test_the_bar_has_ten_steps() -> None:
    assert bar(0, 100) == ".........."
    assert bar(100, 100) == "##########"
    assert bar(46, 100) == "#####....."
    assert bar(250, 100) == "##########"  # clamped, never longer
    assert bar(5, 0) == ""


# --- reading back ---------------------------------------------------------------------------------


def test_a_drawn_line_moves_the_meter_and_the_delta_is_computed_not_believed() -> None:
    trust = a_tracker()

    moved = absorb([trust], "She laughs.\n\n[Trust] #####..... 43/100 | Δ +50 | told the truth", 9)

    assert moved == 1
    assert (trust.value, trust.delta, trust.note, trust.updated_at_sequence) == (
        43,
        3,
        "told the truth",
        9,
    )


def test_a_value_past_the_range_is_clamped_rather_than_stored() -> None:
    trust = a_tracker()

    absorb([trust], "[Trust] ########## 250/100 | Δ +210 | overwhelmed", 9)

    assert (trust.value, trust.delta) == (100, 60)


def test_only_meters_the_story_has_are_touched_whatever_the_model_invents() -> None:
    trust = a_tracker()

    moved = absorb(
        [trust], "[Suspicion] ##........ 20/100 | Δ +20 | new\n[trust] 41/100 | Δ 1 | hm", 9
    )

    assert moved == 1
    assert trust.value == 41  # matched without case
    assert trust.note == "hm"


def test_the_bar_glyphs_and_the_word_delta_are_not_required() -> None:
    trust = a_tracker()

    absorb([trust], "[Trust] ♥♥♥♥♡♡♡♡♡♡ 42 / 100 | delta +2 | a small kindness", 9)

    assert (trust.value, trust.note) == (42, "a small kindness")


def test_an_unchanged_value_moves_nothing_and_keeps_the_old_note() -> None:
    trust = a_tracker()
    trust.note = "earlier"

    moved = absorb([trust], "[Trust] ####...... 40/100 | Δ 0 | nothing earned", 9)

    assert moved == 0
    assert (trust.note, trust.updated_at_sequence) == ("earlier", None)


def test_the_note_is_trimmed_and_capped() -> None:
    trust = a_tracker()

    absorb([trust], "[Trust] 41/100 | Δ 1 | — " + "x" * 300, 9)

    assert trust.note is not None
    assert 190 <= len(trust.note) <= trackers.NOTE_LENGTH
    assert trust.note.startswith("xxx")


def test_the_set_command_takes_the_value_as_the_last_word() -> None:
    assert split_command("Trust in Rowan 40") == ("Trust in Rowan", 40)
    assert split_command("Heat 2.5") == ("Heat", 2.5)
    assert split_command("Trust forty") is None
    assert split_command("40") is None


# --- the API -------------------------------------------------------------------------------------


async def test_a_meter_is_added_listed_set_by_hand_and_removed(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)

    added = await client.post(
        f"/stories/{story.id}/trackers",
        json={"name": "Trust", "value": 40, "means": "how far she trusts Rowan"},
    )
    listed = await client.get(f"/stories/{story.id}/trackers")
    changed = await client.patch(f"/stories/{story.id}/trackers/trust", json={"value": 55})
    removed = await client.delete(f"/stories/{story.id}/trackers/Trust")
    after = await client.get(f"/stories/{story.id}/trackers")

    assert added.status_code == 201
    assert added.json()["name"] == "Trust"
    assert (added.json()["value"], added.json()["max"], added.json()["delta"]) == (40, 100, 0)
    assert added.json()["updated_at_sequence"] is None
    assert [t["name"] for t in listed.json()] == ["Trust"]
    assert changed.status_code == 200
    assert (changed.json()["value"], changed.json()["delta"], changed.json()["note"]) == (
        55,
        15,
        "set by hand",
    )
    assert changed.json()["updated_at_sequence"] == 1  # the opening is the newest turn
    assert removed.status_code == 204
    assert after.json() == []


async def test_two_meters_cannot_share_a_name_whatever_the_case(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Trust"})

    response = await client.post(f"/stories/{story.id}/trackers", json={"name": "TRUST"})

    assert response.status_code == 409


async def test_a_value_outside_the_range_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Heat", "max": 10})

    too_far = await client.patch(f"/stories/{story.id}/trackers/Heat", json={"value": 11})
    below = await client.post(f"/stories/{story.id}/trackers", json={"name": "Cold", "value": -1})
    no_range = await client.post(f"/stories/{story.id}/trackers", json={"name": "Flat", "max": 0})

    assert too_far.status_code == 422
    assert too_far.json()["detail"] == "Heat runs from 0 to 10."
    assert below.status_code == 422
    assert no_range.status_code == 422


async def test_a_meter_that_does_not_exist_is_a_404(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)

    assert (
        await client.patch(f"/stories/{story.id}/trackers/Hope", json={"value": 1})
    ).status_code == 404
    assert (await client.delete(f"/stories/{story.id}/trackers/Hope")).status_code == 404


async def test_the_tracker_command_sets_a_meter_and_stores_no_turn(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Trust in Rowan"})

    streamed = await send(client, story.id, "/tracker trust in rowan 40")

    assert streamed.done == {"kind": "said", "text": "Trust in Rowan is now 40."}
    [trust] = await stored(session, story)
    assert (trust.value, trust.delta, trust.note) == (40, 40, "set by hand")
    assert len(await messages(session, story, hidden=True)) == 1  # the opening only
    assert model.calls == []


async def test_the_tracker_command_refuses_what_it_cannot_read(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Trust"})

    not_a_number = await send(client, story.id, "/tracker Trust forty")
    unknown = await send(client, story.id, "/tracker Hope 40")
    nothing = await send(client, story.id, "/tracker")

    assert not_a_number.status == 422
    assert "the value has to be a number" in not_a_number.last[1]["detail"]
    assert unknown.status == 404
    assert nothing.status == 422
    assert "/tracker <name> <value>" in nothing.last[1]["detail"]


# --- the round trip through a turn ------------------------------------------------------------


async def test_a_turn_carries_the_meter_in_and_reads_it_back_out(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Trust", "value": 40})
    model.says(
        "She looks up, and this time she answers.\n\n[Trust] #####..... 43/100 | Δ +3 | answered"
    )

    streamed = await send(client, story.id, "I ask her name.")

    sent = model.last["messages"]
    layer = next(m for m in sent if m["content"].startswith(HEADER))
    assert layer["role"] == "system"
    assert "[Trust] ####...... 40/100 | Δ 0 | —" in layer["content"]
    assert sent.index(layer) == len(sent) - 1  # after the history, nothing else after it
    [trust] = await stored(session, story)
    reply = streamed.done["reply"]
    assert (trust.value, trust.delta, trust.note) == (43, 3, "answered")
    assert trust.updated_at_sequence == reply["sequence"]
    # The drawn line stays in the reply the model wrote.
    assert reply["text"].endswith("[Trust] #####..... 43/100 | Δ +3 | answered")
    audit = (await client.get(f"/stories/{story.id}/audit")).json()
    assert " · trackers " in audit["turns"][0]["context"]


async def test_a_meter_survives_the_turns_that_showed_it_being_compressed_away(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    """The value lives in the table, not in the transcript: when the turns that last drew the
    meter are summarised, the next prompt still starts from where it stood."""
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Trust", "value": 40})
    model.summarises("Stretch.").extracts().says("Hm.\n\n[Trust] ####...... 42/100 | Δ +2 | hm")

    await send(client, story.id, "I come in.")

    reply_call = model.calls[2]
    layer = next(m for m in reply_call["messages"] if m["content"].startswith(HEADER))
    assert "[Trust] ####...... 40/100" in layer["content"]
    [trust] = await stored(session, story)
    assert trust.value == 42
    kinds = sorted(row.kind for row in await ledger(session, story))
    assert len(kinds) == 3  # a summary, an extraction, a reply — the meter cost no call


async def test_a_question_sees_the_meters_but_does_not_move_them(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await client.post(f"/stories/{story.id}/trackers", json={"name": "Trust", "value": 40})
    model.says("About 40, going by the last turn. [Trust] 90/100 | Δ +50 | guess")

    await send(client, story.id, "/ask how much does she trust me?")

    assert any(m["content"].startswith(HEADER) for m in model.last["messages"])
    [trust] = await stored(session, story)
    assert trust.value == 40
