"""Dials: how a story's replies are written, set per story, each wired to its strongest lever.

"Be more varied", written into a prompt, is the weakest way to move a model. Temperature moves
it; so does the token ceiling. So each dial declares its lever: `prompt` puts the chosen text in
the directives layer, `sampler` sets an API parameter and injects nothing, `both` does one of
each per level. The pack is data (`dials.json`, shipped with the package): adding a dial is not a
code change. A story stores only the values it changed; everything else is the pack's default.
"""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from importlib import resources
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.deps import Session
from lustjinn.models import DialValue
from lustjinn.stories import visible_story

Json = dict[str, Any]


class Kind(StrEnum):
    SCALE = "scale"
    """Five steps, read by index. Never fewer: a short scale would make the top of the dial
    quietly mean the bottom."""
    TOGGLE = "toggle"
    """On injects the dial's text; off injects nothing."""
    CHOICE = "choice"
    """Named options, one active."""
    LIST = "list"
    """Reader-supplied items rendered through a template."""
    TEXT = "text"
    """One free value rendered through a template."""


class Lever(StrEnum):
    PROMPT = "prompt"
    SAMPLER = "sampler"
    """The chosen value becomes an API parameter. Nothing is injected: a number the model can
    see is a number it performs."""
    BOTH = "both"


SCALE_STEPS = 5
MAPS = ("temperature", "max_tokens", "frequency_penalty")
"""The sampler parameters a dial may set."""


@dataclass(frozen=True)
class Level:
    label: str
    text: str | None = None
    """Injected for prompt levers; None on a sampler-only level."""
    value: float | None = None
    """The sampler value; None on a prompt-only level."""
    description: str | None = None
    """Screen-only, for sampler levers whose text never travels."""


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    text: str


@dataclass(frozen=True, kw_only=True)
class Dial:
    """One control, with its documentation carried as data: the settings screen renders it."""

    key: str
    kind: Kind
    lever: Lever
    title: str
    maps: str | None = None
    enabled: bool = True
    """Disabled is pinned, not off: the default still applies on every prompt, and a stored
    value survives to resurface the day the dial is re-enabled."""
    default: str | None = None
    """What applies when a story has not chosen, in stored form: a level index for a scale,
    `true`/`false` for a toggle, an option key, a JSON array for a list, the raw text. None
    means inject nothing — the model's own behaviour."""
    help: str = ""
    levels: tuple[Level, ...] = ()
    options: tuple[Option, ...] = ()
    on_text: str | None = None
    template: str | None = None
    accepts: str | None = None
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skipped:
    """A dial the pack could not use, and why — surfaced rather than swallowed."""

    key: str
    reason: str


@dataclass(frozen=True)
class Pack:
    dials: tuple[Dial, ...]
    """In file order, which is the order their text enters the prompt."""
    skipped: tuple[Skipped, ...] = ()

    def find(self, key: str) -> Dial | None:
        wanted = key.strip().lower()
        return next((d for d in self.dials if d.key.lower() == wanted), None)


# --- reading a pack ---------------------------------------------------------------------------


class UnusableError(ValueError):
    """A dial that cannot be used as declared. Skipped whole, never used in part."""


def _text(source: Json, key: str) -> str | None:
    value = source.get(key)
    return value if isinstance(value, str) else None


def _enum[E: StrEnum](kind: type[E], raw: str | None, what: str) -> E:
    try:
        return kind((raw or "").lower())
    except ValueError:
        raise UnusableError(f"unknown {what} '{raw}'") from None


def _levels(raw: object, lever: Lever) -> tuple[Level, ...]:
    if not isinstance(raw, list):
        raise UnusableError(f"a scale needs exactly {SCALE_STEPS} complete levels")
    levels: list[Level] = []
    for node in raw:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(node, dict):
            raise UnusableError(f"a scale needs exactly {SCALE_STEPS} complete levels")
        level: Json = node  # pyright: ignore[reportUnknownVariableType]
        label = _text(level, "label")
        text = _text(level, "text")
        value = level.get("value")
        number = float(value) if isinstance(value, int | float) else None
        # Each level carries what its lever spends: text for the prompt, a value for the
        # sampler, both for both. A level missing its half breaks the whole scale.
        complete = {
            Lever.PROMPT: bool(text and text.strip()),
            Lever.SAMPLER: number is not None,
            Lever.BOTH: bool(text and text.strip()) and number is not None,
        }[lever]
        if not label or not complete:
            raise UnusableError(f"a scale needs exactly {SCALE_STEPS} complete levels")
        levels.append(Level(label, text, number, _text(level, "description")))
    if len(levels) != SCALE_STEPS:
        raise UnusableError(f"a scale needs exactly {SCALE_STEPS} complete levels")
    return tuple(levels)


def _options(raw: object) -> tuple[Option, ...]:
    if not isinstance(raw, dict):
        raise UnusableError("a choice needs at least two options, each with text")
    options: list[Option] = []
    for key, node in raw.items():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(key, str) or not isinstance(node, dict):
            raise UnusableError("a choice needs at least two options, each with text")
        option: Json = node  # pyright: ignore[reportUnknownVariableType]
        text = _text(option, "text")
        if not text:
            raise UnusableError("a choice needs at least two options, each with text")
        options.append(Option(key, _text(option, "label") or key, text))
    if len(options) < 2:
        raise UnusableError("a choice needs at least two options, each with text")
    return tuple(options)


def _stored_default(kind: Kind, raw: object) -> str | None:
    """A JSON default in the stored form the value store uses."""
    if raw is None:
        return None
    if isinstance(raw, list) and kind is Kind.LIST:
        return json.dumps(raw)
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, int | float):
        return str(int(raw)) if float(raw).is_integer() else str(raw)
    if isinstance(raw, str):
        return raw
    return None


def _examples(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    found: list[str] = []
    for example in raw:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(example, str):
            found.append(example)
        elif isinstance(example, list):
            found.append(", ".join(str(item) for item in example))  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return tuple(found)


def _read(key: str, raw: Json) -> Dial:
    kind = _enum(Kind, _text(raw, "kind"), "kind")
    lever = _enum(Lever, _text(raw, "lever"), "lever")
    maps = _text(raw, "maps")
    if lever is not Lever.PROMPT and maps not in MAPS:
        raise UnusableError(
            'a sampler lever needs "maps": temperature, max_tokens or frequency_penalty'
        )
    template = _text(raw, "template")
    on_text = _text(raw, "on")
    levels = _levels(raw.get("levels"), lever) if kind is Kind.SCALE else ()
    options = _options(raw.get("options")) if kind is Kind.CHOICE else ()
    if kind is Kind.TOGGLE and not (on_text and on_text.strip()):
        raise UnusableError('a toggle needs "on" text')
    if kind is Kind.LIST and (template is None or "{items}" not in template):
        raise UnusableError("a list needs a template containing {items}")
    if kind is Kind.TEXT and (template is None or "{value}" not in template):
        raise UnusableError("a text needs a template containing {value}")
    enabled = raw.get("enabled")
    return Dial(
        key=key,
        kind=kind,
        lever=lever,
        maps=maps if lever is not Lever.PROMPT else None,
        enabled=enabled if isinstance(enabled, bool) else True,
        default=_stored_default(kind, raw.get("default")),
        title=_text(raw, "title") or key,
        help=_text(raw, "help") or "",
        levels=levels,
        options=options,
        on_text=on_text,
        template=template,
        accepts=_text(raw, "accepts"),
        examples=_examples(raw.get("examples")),
    )


def parse(text: str) -> Pack:
    """Reads a pack. A dial that cannot be used is skipped whole with its reason; text that is
    not JSON at all raises `json.JSONDecodeError`."""
    root: object = json.loads(text)
    declared = root.get("dials") if isinstance(root, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(declared, dict):
        return Pack((), (Skipped("(file)", 'no "dials" object'),))
    dials: list[Dial] = []
    skipped: list[Skipped] = []
    for key, node in declared.items():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(key, str):
            continue
        if not isinstance(node, dict):
            skipped.append(Skipped(key, "not an object"))
            continue
        try:
            dials.append(_read(key, node))  # pyright: ignore[reportUnknownArgumentType]
        except UnusableError as why:
            skipped.append(Skipped(key, str(why)))
    return Pack(tuple(dials), tuple(skipped))


@lru_cache
def shipped() -> Pack:
    """The pack shipped with the package. Read once; it never changes while the app runs."""
    return parse(resources.files("lustjinn").joinpath("dials.json").read_text(encoding="utf-8"))


# --- the engine: from a pack and a story's values to a prompt layer and sampler settings ------


def effective(dial: Dial, values: Mapping[str, str]) -> str | None:
    """The value in force: the story's own while the dial is enabled, else the default."""
    stored = values.get(dial.key)
    return stored if dial.enabled and stored is not None else dial.default


def level_index(dial: Dial, value: str | None) -> int | None:
    """A stored scale value as a level index, or None when it is not one the dial has."""
    if value is None:
        return None
    try:
        index = int(value.strip())
    except ValueError:
        return None
    return index if 0 <= index < len(dial.levels) else None


def is_on(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def items(value: str | None) -> list[str]:
    """A stored list value back into its items; empty when it is not a list."""
    if not value or not value.strip():
        return []
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item.strip() for item in parsed if isinstance(item, str) and item.strip()]  # pyright: ignore[reportUnknownVariableType]


def store_items(raw: list[str]) -> str | None:
    kept = [item.strip() for item in raw if item.strip()]
    return json.dumps(kept) if kept else None


def _option(dial: Dial, value: str | None) -> Option | None:
    wanted = (value or "").strip().lower()
    return next((o for o in dial.options if o.key.lower() == wanted), None)


def accept(dial: Dial, raw: str) -> str | None:
    """What a person typed, in stored form — or None when the dial does not take it.

    Validated rather than trusted: a value the engine cannot read would be stored and then
    silently say nothing on every turn.
    """
    typed = raw.strip()
    match dial.kind:
        case Kind.SCALE:
            return typed if level_index(dial, typed) is not None else None
        case Kind.TOGGLE:
            return typed.lower() if typed.lower() in ("true", "false") else None
        case Kind.CHOICE:
            found = _option(dial, typed)
            return None if found is None else found.key
        case Kind.LIST:
            return store_items(typed.split(","))
        case Kind.TEXT:
            return typed or None


def accepts(dial: Dial) -> str:
    """What the dial takes, in words, for a refusal that helps."""
    match dial.kind:
        case Kind.SCALE:
            names = ", ".join(level.label for level in dial.levels)
            return f"a level from 0 to {SCALE_STEPS - 1} ({names})"
        case Kind.TOGGLE:
            return "true or false"
        case Kind.CHOICE:
            return "one of " + ", ".join(option.key for option in dial.options)
        case Kind.LIST:
            return dial.accepts or "items separated by commas"
        case Kind.TEXT:
            return dial.accepts or "some text"


def label(dial: Dial, value: str | None) -> str | None:
    """A stored value the way a screen shows it: the level's or option's label, On/Off, the
    items, or the value itself."""
    if value is None:
        return None
    match dial.kind:
        case Kind.SCALE:
            index = level_index(dial, value)
            return value if index is None else dial.levels[index].label
        case Kind.TOGGLE:
            return "On" if is_on(value) else "Off"
        case Kind.CHOICE:
            found = _option(dial, value)
            return value if found is None else found.label
        case Kind.LIST:
            return ", ".join(items(value))
        case Kind.TEXT:
            return value


def directives(pack: Pack, values: Mapping[str, str]) -> str | None:
    """Every prompt-lever dial in force, rendered into the directives layer's text.

    The one-line dials read as a block of their own, ahead of the paragraph-shaped ones, in pack
    order — cache-stable until a dial moves. Sampler levers never render. A stored value the pack
    cannot read — a level out of range, an option since renamed — says nothing rather than
    something wrong.
    """
    lines: list[str] = []
    blocks: list[str] = []
    for dial in pack.dials:
        if dial.lever is Lever.SAMPLER or (value := effective(dial, values)) is None:
            continue
        match dial.kind:
            case Kind.SCALE if (index := level_index(dial, value)) is not None:
                level = dial.levels[index]
                lines.append(f"{dial.title}: {level.label} — {level.text}.")
            case Kind.CHOICE if (option := _option(dial, value)) is not None:
                lines.append(f"{dial.title}: {option.text}.")
            case Kind.TOGGLE if is_on(value) and dial.on_text:
                blocks.append(dial.on_text.strip())
            case Kind.LIST if (found := items(value)) and dial.template:
                blocks.append(dial.template.replace("{items}", ", ".join(found)).strip())
            case Kind.TEXT if value.strip() and dial.template:
                blocks.append(dial.template.replace("{value}", value.strip()).strip())
            case _:
                pass
    parts = (["\n".join(lines)] if lines else []) + blocks
    return "\n\n".join(parts) if parts else None


@dataclass(frozen=True)
class Sampler:
    """The sampler parameters the dials ask for; None where no dial speaks to one."""

    temperature: float | None = None
    max_tokens: int | None = None
    frequency_penalty: float | None = None


def sampler(pack: Pack, values: Mapping[str, str]) -> Sampler:
    chosen: dict[str, float] = {}
    for dial in pack.dials:
        if dial.lever is Lever.PROMPT or dial.kind is not Kind.SCALE or dial.maps is None:
            continue
        index = level_index(dial, effective(dial, values))
        if index is None or (value := dial.levels[index].value) is None:
            continue
        chosen[dial.maps] = value
    ceiling = chosen.get("max_tokens")
    return Sampler(
        temperature=chosen.get("temperature"),
        max_tokens=None if ceiling is None else int(ceiling),
        frequency_penalty=chosen.get("frequency_penalty"),
    )


# --- a story's values ---------------------------------------------------------------------------


async def values_of(session: AsyncSession, story_id: uuid.UUID) -> dict[str, str]:
    rows = await session.scalars(select(DialValue).where(DialValue.story_id == story_id))
    return {row.key: row.value for row in rows}


async def of_story(session: AsyncSession, story_id: uuid.UUID) -> tuple[str | None, Sampler]:
    """A story's dials: rendered for the directives layer, and resolved for the sampler."""
    pack = shipped()
    values = await values_of(session, story_id)
    return directives(pack, values), sampler(pack, values)


# --- the API --------------------------------------------------------------------------------------

router = APIRouter(tags=["dials"])


class LevelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    text: str | None
    value: float | None
    description: str | None


class OptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    text: str


class DialOut(BaseModel):
    """A dial of the pack, read straight off its `Dial`, its levels and options with it."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    kind: Kind
    lever: Lever
    maps: str | None
    enabled: bool
    default: str | None
    title: str
    help: str
    levels: list[LevelOut]
    options: list[OptionOut]
    on_text: str | None
    template: str | None
    accepts: str | None
    examples: list[str]


class StoryDialOut(BaseModel):
    """One dial as it stands for one story."""

    key: str
    title: str
    kind: Kind
    enabled: bool
    stored: str | None
    """What the story chose; None when it never did, or cleared it."""
    effective: str | None
    """What applies on the next turn: the stored value while enabled, else the default."""
    label: str | None
    """The effective value as a screen shows it."""


class SetDial(BaseModel):
    value: str


def _story_dial_out(dial: Dial, values: Mapping[str, str]) -> StoryDialOut:
    in_force = effective(dial, values)
    return StoryDialOut(
        key=dial.key,
        title=dial.title,
        kind=dial.kind,
        enabled=dial.enabled,
        stored=values.get(dial.key),
        effective=in_force,
        label=label(dial, in_force),
    )


def _known(key: str) -> Dial:
    dial = shipped().find(key)
    if dial is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"There is no dial called {key}.")
    return dial


@router.get("/dials")
async def read_pack() -> list[DialOut]:
    """The pack: every dial, with the text each level or option sends. The text shown on a
    screen and the text the model receives are the same."""
    return [DialOut.model_validate(dial) for dial in shipped().dials]


@router.get("/stories/{story_id}/dials")
async def read_story_dials(story_id: uuid.UUID, session: Session) -> list[StoryDialOut]:
    """Every dial as it stands for this story: what was chosen, and what applies."""
    await visible_story(session, story_id)
    values = await values_of(session, story_id)
    return [_story_dial_out(dial, values) for dial in shipped().dials]


@router.put("/stories/{story_id}/dials/{key}")
async def set_dial(story_id: uuid.UUID, key: str, body: SetDial, session: Session) -> StoryDialOut:
    """Sets one dial for this story. The value is checked against the dial before it is kept:
    a level index, true/false, an option key, comma-separated items, or text."""
    await visible_story(session, story_id)
    dial = _known(key)
    if not dial.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{dial.title} is disabled in the pack, so it is pinned to its default.",
        )
    stored = accept(dial, body.value)
    if stored is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{dial.title} takes {accepts(dial)}."
        )
    row = await session.scalar(
        select(DialValue).where(DialValue.story_id == story_id, DialValue.key == dial.key)
    )
    if row is None:
        session.add(DialValue(story_id=story_id, key=dial.key, value=stored))
    else:
        row.value = stored
        row.updated_at = datetime.now(tz=UTC)
    await session.commit()
    return _story_dial_out(dial, await values_of(session, story_id))


@router.delete("/stories/{story_id}/dials/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_dial(story_id: uuid.UUID, key: str, session: Session) -> None:
    """Returns the dial to the pack's default. A dial never set and a dial cleared are the same
    state, so the row goes rather than holding a null."""
    await visible_story(session, story_id)
    dial = _known(key)
    row = await session.scalar(
        select(DialValue).where(DialValue.story_id == story_id, DialValue.key == dial.key)
    )
    if row is not None:
        await session.delete(row)
        await session.commit()
