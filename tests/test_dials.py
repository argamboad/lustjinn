"""Dials: a pack of data, set per story, each wired to its lever — the prompt or the sampler."""

import json
from collections.abc import Callable

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import dials
from lustjinn.context import PERSONA_FRAME
from lustjinn.dials import Kind, Lever, Pack, accept, directives, effective, label, sampler
from lustjinn.models import DialValue
from lustjinn.settings import Settings
from scripts.seed_dummy import Dummy
from tests.scripted_model import ScriptedModel
from tests.streaming import send
from tests.test_summaries import a_budget_that_holds, a_long_story
from tests.test_turns import a_played_story


def a_pack(**declared: object) -> Pack:
    return dials.parse(json.dumps({"dials": declared}))


def five(**extra: object) -> list[dict[str, object]]:
    return [{"label": f"L{i}", "text": f"text {i}", "value": i, **extra} for i in range(5)]


# --- reading the pack --------------------------------------------------------------------------


def test_the_shipped_pack_reads_whole() -> None:
    pack = dials.shipped()

    assert pack.skipped == ()
    assert len(pack.dials) == 16
    assert [d.key for d in pack.dials[:4]] == [
        "lust",
        "response-length",
        "creativity",
        "inner-thoughts",
    ]
    creativity = pack.find("Creativity")
    assert creativity is not None
    assert (creativity.lever, creativity.maps) == (Lever.SAMPLER, "temperature")
    assert [level.value for level in creativity.levels] == [0.6, 0.8, 1.0, 1.2, 1.4]
    length = pack.find("response-length")
    assert length is not None
    assert (length.lever, length.maps) == (Lever.BOTH, "max_tokens")
    assert [level.value for level in length.levels] == [200, 450, 900, 1600, 2600]
    guard = pack.find("agency-guard")
    assert guard is not None
    assert not guard.enabled


def test_a_scale_without_exactly_five_complete_levels_is_skipped_whole() -> None:
    """Levels are read by index: a four-level scale would make the top quietly mean the bottom."""
    pack = a_pack(
        short={"kind": "scale", "lever": "prompt", "levels": five()[:4]},
        halved={
            "kind": "scale",
            "lever": "both",
            "maps": "max_tokens",
            "levels": [{"label": "A", "value": 1}, *five()[1:]],
        },
    )

    assert pack.dials == ()
    assert [s.key for s in pack.skipped] == ["short", "halved"]
    assert all("exactly 5 complete levels" in s.reason for s in pack.skipped)


def test_a_sampler_lever_needs_a_parameter_to_set() -> None:
    pack = a_pack(
        loose={"kind": "scale", "lever": "sampler", "levels": five()},
        odd={"kind": "scale", "lever": "sampler", "maps": "top_p", "levels": five()},
    )

    assert pack.dials == ()
    assert all('needs "maps"' in s.reason for s in pack.skipped)


def test_each_kind_needs_its_own_part() -> None:
    pack = a_pack(
        mute={"kind": "toggle", "lever": "prompt"},
        lonely={"kind": "choice", "lever": "prompt", "options": {"one": {"text": "x"}}},
        holey={"kind": "list", "lever": "prompt", "template": "Never: {value}"},
        blank={"kind": "text", "lever": "prompt", "template": "Write in {items}"},
        alien={"kind": "knob", "lever": "prompt"},
        pulled={"kind": "scale", "lever": "rope", "levels": five()},
    )

    assert pack.dials == ()
    assert {s.key: s.reason for s in pack.skipped} == {
        "mute": 'a toggle needs "on" text',
        "lonely": "a choice needs at least two options, each with text",
        "holey": "a list needs a template containing {items}",
        "blank": "a text needs a template containing {value}",
        "alien": "unknown kind 'knob'",
        "pulled": "unknown lever 'rope'",
    }


def test_a_file_without_a_dials_object_is_one_skipped_entry() -> None:
    pack = dials.parse('{"version": 1}')

    assert pack.dials == ()
    assert pack.skipped == (dials.Skipped("(file)", 'no "dials" object'),)


def test_defaults_are_kept_in_stored_form() -> None:
    pack = a_pack(
        heat={"kind": "scale", "lever": "prompt", "levels": five(), "default": 2},
        quiet={"kind": "toggle", "lever": "prompt", "on": "Hush.", "default": True},
        veils={"kind": "list", "lever": "prompt", "template": "{items}", "default": ["a", "b"]},
    )

    assert [d.default for d in pack.dials] == ["2", "true", '["a", "b"]']


# --- the engine ----------------------------------------------------------------------------------


def test_a_stored_value_wins_while_the_dial_is_enabled() -> None:
    pack = a_pack(
        heat={"kind": "scale", "lever": "prompt", "levels": five(), "default": "2"},
        pinned={
            "kind": "scale",
            "lever": "prompt",
            "levels": five(),
            "default": "2",
            "enabled": False,
        },
    )
    heat, pinned = pack.dials

    assert effective(heat, {}) == "2"
    assert effective(heat, {"heat": "4"}) == "4"
    # Disabled is pinned, not off: the default applies and the stored value is merely overridden.
    assert effective(pinned, {"pinned": "4"}) == "2"


def test_directives_render_lines_first_then_blocks_in_pack_order() -> None:
    pack = dials.shipped()
    values = {
        "inner-thoughts": "true",
        "lust": "3",
        "creativity": "4",  # sampler only: never rendered
        "veils": '["graphic violence", "character death"]',
        "pov": "third-past",
        "language": "Costa Rican Spanish",
    }

    rendered = directives(pack, values)

    assert rendered is not None
    lines, *blocks = rendered.split("\n\n")
    assert lines == (
        "Lust: Explicit — sexually forward, fast escalation, anatomically detailed.\n"
        "Point of view: narrate in third person limited, past tense."
    )
    assert blocks[0].startswith("After each character speaks and acts")
    assert blocks[-2] == (
        "Never depict on the page: graphic violence, character death. When the story reaches "
        "one, cut away and resume after."
    )
    assert blocks[-1] == (
        "Write every reply in Costa Rican Spanish, whatever language the cards or the user use."
    )
    assert "Creativity" not in rendered
    assert "1.4" not in rendered


def test_nothing_set_renders_nothing() -> None:
    assert directives(dials.shipped(), {}) is None
    assert directives(dials.shipped(), {"inner-thoughts": "false", "veils": "[]"}) is None


def test_a_value_the_pack_cannot_read_says_nothing_rather_than_something_wrong() -> None:
    rendered = directives(dials.shipped(), {"lust": "9", "pov": "fourth-wall", "lust ": "1"})

    assert rendered is None


def test_the_sampler_reads_the_scales_wired_to_it() -> None:
    pack = dials.shipped()

    assert sampler(pack, {}) == dials.Sampler()
    assert sampler(pack, {"creativity": "4", "response-length": "0", "anti-loop": "2"}) == (
        dials.Sampler(temperature=1.4, max_tokens=200, frequency_penalty=0.4)
    )
    assert sampler(pack, {"lust": "4"}) == dials.Sampler()  # a prompt lever is not a sampler


def test_what_a_person_types_is_checked_against_the_dial() -> None:
    pack = dials.shipped()
    lust, _length, _creativity, thoughts = pack.dials[:4]
    veils, pov = pack.find("veils"), pack.find("pov")
    language = pack.find("language")
    assert veils is not None
    assert pov is not None
    assert language is not None

    assert accept(lust, " 3 ") == "3"
    assert accept(lust, "7") is None
    assert accept(lust, "Explicit") is None  # by index, never by label
    assert accept(thoughts, "True") == "true"
    assert accept(thoughts, "yes") is None
    assert accept(pov, "THIRD-PAST") == "third-past"
    assert accept(pov, "fourth") is None
    assert accept(veils, "graphic violence, , character death ") == (
        '["graphic violence", "character death"]'
    )
    assert accept(veils, " , ") is None
    assert accept(language, "  ") is None
    assert accept(language, "Spanish") == "Spanish"


def test_labels_are_what_a_screen_shows() -> None:
    pack = dials.shipped()
    lust, _length, _creativity, thoughts = pack.dials[:4]
    veils = pack.find("veils")
    assert veils is not None

    assert label(lust, "3") == "Explicit"
    assert label(lust, None) is None
    assert label(thoughts, "true") == "On"
    assert label(veils, '["a", "b"]') == "a, b"


# --- the API -------------------------------------------------------------------------------------


async def stored_values(session: AsyncSession, story_id: object) -> dict[str, str]:
    rows = await session.scalars(
        select(DialValue)
        .where(DialValue.story_id == story_id)
        .execution_options(populate_existing=True)
    )
    return {row.key: row.value for row in rows}


async def test_the_pack_is_listed_with_the_text_each_level_sends(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.get("/dials")

    assert response.status_code == 200
    listed = response.json()
    assert [d["key"] for d in listed][:4] == [
        "lust",
        "response-length",
        "creativity",
        "inner-thoughts",
    ]
    assert listed[0]["levels"][3] == {
        "label": "Explicit",
        "text": "sexually forward, fast escalation, anatomically detailed",
        "value": None,
        "description": None,
    }
    assert listed[2]["levels"][4] == {
        "label": "Wild",
        "text": None,
        "value": 1.4,
        "description": "maximum variation",
    }


async def test_the_pack_needs_a_token(anonymous: httpx2.AsyncClient) -> None:
    assert (await anonymous.get("/dials")).status_code == 401


async def test_a_story_sets_a_dial_and_sees_it_in_force(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)

    before = (await client.get(f"/stories/{story.id}/dials")).json()
    set_to = await client.put(f"/stories/{story.id}/dials/lust", json={"value": "3"})
    after = (await client.get(f"/stories/{story.id}/dials")).json()

    assert before[0] == {
        "key": "lust",
        "title": "Lust",
        "kind": "scale",
        "enabled": True,
        "stored": None,
        "effective": None,
        "label": None,
    }
    assert set_to.status_code == 200
    assert set_to.json() == {**before[0], "stored": "3", "effective": "3", "label": "Explicit"}
    assert after[0] == set_to.json()
    assert await stored_values(session, story.id) == {"lust": "3"}


async def test_setting_a_dial_again_replaces_its_value(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.put(f"/stories/{story.id}/dials/lust", json={"value": "3"})

    response = await client.put(f"/stories/{story.id}/dials/LUST", json={"value": "1"})

    assert response.status_code == 200
    assert await stored_values(session, story.id) == {"lust": "1"}  # the pack's key, not as typed


async def test_a_value_the_dial_does_not_take_is_refused_with_what_it_takes(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)

    response = await client.put(f"/stories/{story.id}/dials/lust", json={"value": "hot"})

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Lust takes a level from 0 to 4 (Cold, Friendly, Flirty, Explicit, Unhinged)."
    )
    assert await stored_values(session, story.id) == {}


async def test_an_unknown_dial_is_a_404(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    story = await a_played_story(session)

    response = await client.put(f"/stories/{story.id}/dials/volume", json={"value": "11"})

    assert response.status_code == 404
    assert response.json()["detail"] == "There is no dial called volume."


async def test_a_disabled_dial_is_pinned_and_cannot_be_set(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)

    response = await client.put(f"/stories/{story.id}/dials/agency-guard", json={"value": "4"})

    assert response.status_code == 409
    assert "pinned to its default" in response.json()["detail"]


async def test_clearing_a_dial_returns_it_to_the_default_and_deletes_the_row(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_played_story(session)
    await client.put(f"/stories/{story.id}/dials/lust", json={"value": "3"})

    cleared = await client.delete(f"/stories/{story.id}/dials/lust")
    again = await client.delete(f"/stories/{story.id}/dials/lust")

    assert (cleared.status_code, again.status_code) == (204, 204)
    assert await stored_values(session, story.id) == {}
    listed = (await client.get(f"/stories/{story.id}/dials")).json()
    assert listed[0]["stored"] is None
    assert listed[0]["effective"] is None


async def test_dials_belong_to_a_story_that_exists(client: httpx2.AsyncClient) -> None:
    missing = "01a10d31-0000-7000-8000-000000000000"

    assert (await client.get(f"/stories/{missing}/dials")).status_code == 404
    assert (
        await client.put(f"/stories/{missing}/dials/lust", json={"value": "1"})
    ).status_code == 404


# --- each lever reaches where it should --------------------------------------------------------


async def test_a_prompt_lever_reaches_the_directives_layer_after_the_persona(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, dummy: Dummy
) -> None:
    story = await a_played_story(session)
    await client.put(f"/stories/{story.id}/dials/lust", json={"value": "3"})
    await client.put(f"/stories/{story.id}/dials/inner-thoughts", json={"value": "true"})
    model.says("She looks up.")

    await send(client, story.id, "I come in.")

    sent = model.last["messages"]
    assert sent[0]["content"] == dummy.card
    assert sent[1]["content"].startswith(PERSONA_FRAME)
    assert sent[2]["role"] == "system"
    assert sent[2]["content"].startswith(
        "Lust: Explicit — sexually forward, fast escalation, anatomically detailed.\n\n"
        "After each character speaks and acts"
    )
    assert sent[3] == {"role": "assistant", "content": dummy.opening}


async def test_a_sampler_lever_reaches_the_request_and_never_the_prompt(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await client.put(f"/stories/{story.id}/dials/creativity", json={"value": "4"})
    await client.put(f"/stories/{story.id}/dials/anti-loop", json={"value": "2"})
    await client.put(f"/stories/{story.id}/dials/response-length", json={"value": "0"})
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    assert model.last["temperature"] == 1.4
    assert model.last["frequency_penalty"] == 0.4
    assert model.last["max_tokens"] == 200
    texts = [m["content"] for m in model.last["messages"]]
    assert not any("Creativity" in t or "Anti-loop" in t for t in texts)
    # "both": the ceiling on the call and a wording the model sees, so the ceiling never cuts
    # a reply the prompt asked to be long.
    assert any(t.startswith("Response length: Minimal — a very brief response") for t in texts)


async def test_with_nothing_set_the_request_carries_the_settings_and_no_penalty(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel, settings: Settings
) -> None:
    story = await a_played_story(session)
    model.says("Hm.")

    await send(client, story.id, "I come in.")

    assert model.last["temperature"] == settings.temperature
    assert model.last["max_tokens"] == settings.max_tokens
    assert "frequency_penalty" not in model.last


async def test_a_summary_stays_cold_whatever_creativity_says(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    model: ScriptedModel,
    tune: Callable[..., Settings],
    dummy: Dummy,
) -> None:
    """A creative summariser invents history the character then believes forever."""
    tune(context_budget=a_budget_that_holds(dummy, 12, tune()))
    story = await a_long_story(session, 30)
    await client.put(f"/stories/{story.id}/dials/creativity", json={"value": "4"})
    model.summarises("Stretch.").extracts().says("Hm.")

    await send(client, story.id, "I come in.")

    summary, extraction, reply = model.calls
    assert summary["temperature"] == 0.3
    assert extraction["temperature"] == 0.2
    assert reply["temperature"] == 1.4


async def test_the_audit_names_the_directives_layer(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await client.put(f"/stories/{story.id}/dials/lust", json={"value": "3"})
    model.says("Hm.")
    await send(client, story.id, "I come in.")

    audit = (await client.get(f"/stories/{story.id}/audit")).json()

    assert " · directives " in audit["turns"][0]["context"]


async def test_a_question_sees_the_dials_but_keeps_its_own_sampling(
    client: httpx2.AsyncClient, session: AsyncSession, model: ScriptedModel
) -> None:
    story = await a_played_story(session)
    await client.put(f"/stories/{story.id}/dials/lust", json={"value": "3"})
    await client.put(f"/stories/{story.id}/dials/creativity", json={"value": "4"})
    model.says("It does not say.")

    await send(client, story.id, "/ask what is her name?")

    texts = [m["content"] for m in model.last["messages"]]
    assert any(t.startswith("Lust: Explicit") for t in texts)
    assert model.last["temperature"] == 0.4


@pytest.mark.parametrize("kind", list(Kind))
def test_every_kind_has_a_way_to_say_what_it_accepts(kind: Kind) -> None:
    dial = next(d for d in dials.shipped().dials if d.kind is kind)

    assert dials.accepts(dial)
