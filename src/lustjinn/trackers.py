"""Meters: a value the story keeps, drawn by the model at the end of each reply and read back.

The loop is: inject the stored value, ask the model to draw the meter having moved it, read
the drawn line and store the new value. That round trip is what keeps a meter honest three
hundred turns later — a card that only instructs the format relies on the model still seeing the
previous value, and it cannot once that turn has been compressed away.

Off by default, and with airp's warning kept: a meter the model can see is a meter it writes
towards. The delta is the part that earns its place — an absolute number tells a reader where
they stand; the delta tells them what the thing they just did was worth.
"""

import re
import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.db import get_session
from lustjinn.models import Message, Tracker
from lustjinn.stories import visible_story

HEADER = (
    "These meters belong to this story. End every reply with all of them, each on its own "
    "line, in exactly this shape, and nothing else after them:"
)
SHAPE = "[NAME] {bar} {value}/{max} | Δ {change} | {reason in three words}"
MOVEMENT = (
    "The values below are where the meters stand right now — start from them. Move one only "
    "when this turn earned it, and by a little: one to three points for an ordinary beat, more "
    "only for something the scene treats as a turning point. A turn that earned nothing shows "
    "Δ 0. The reason is what the reader actually reads, so say what moved it, not how it feels."
)

# Deliberately loose about the bar: models draw hearts, blocks, or nothing at all, and which
# glyph they chose is not worth failing a parse over. The name, the value and the note matter.
RENDERED = re.compile(
    r"\[\s*(?P<name>[^\]\n]{1,120}?)\s*\]\s*(?P<bar>[^\n\d]*?)\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*/\s*(?P<max>\d+(?:\.\d+)?)\s*\|\s*"
    r"(?:Δ|delta)?\s*(?P<delta>[+\-]?\d+(?:\.\d+)?)\s*\|\s*(?P<note>[^\n|]{0,200})",
    re.IGNORECASE,
)
BAR_STEPS = 10
NOTE_LENGTH = 200


def _trim(number: float) -> str:
    """`40` for 40.0, `2.5` for 2.5: the shape the model is asked to draw back."""
    return str(int(number)) if number == int(number) else f"{number:.1f}".rstrip("0").rstrip(".")


def shown(number: float) -> str:
    """A value as a person reads it: `40`, or `2.5`."""
    return _trim(number)


def _signed(delta: float) -> str:
    if delta == 0:
        return "0"
    return f"+{_trim(delta)}" if delta > 0 else _trim(delta)


def bar(value: float, maximum: float) -> str:
    """Ten steps of `#` and `.`."""
    if maximum <= 0:
        return ""
    filled = round(BAR_STEPS * min(max(value / maximum, 0), 1))
    return "#" * filled + "." * (BAR_STEPS - filled)


def render(trackers: Sequence[Tracker]) -> str | None:
    """The meters as the prompt carries them, or None when the story has none."""
    if not trackers:
        return None
    lines = [HEADER, "", SHAPE, "", MOVEMENT, ""]
    for tracker in trackers:
        lines.append(
            f"[{tracker.name}] {bar(tracker.value, tracker.max)} "
            f"{_trim(tracker.value)}/{_trim(tracker.max)} | Δ {_signed(tracker.delta)} "
            f"| {tracker.note or '—'}"
        )
        # What it measures, what the numbers mean, and what constrains it. Without these a
        # meter is a word and a number, and the model re-invents both every turn.
        if tracker.means:
            lines.append(f"    measures: {tracker.means}")
        if tracker.anchors:
            lines.append(f"    scale: {tracker.anchors}")
        if tracker.rule:
            lines.append(f"    rule: {tracker.rule}")
    return "\n".join(lines).rstrip()


def absorb(trackers: Sequence[Tracker], reply: str, sequence: int) -> int:
    """Updates the meters from what the model actually drew. Returns how many moved.

    Only meters that already exist are touched: a model that invents one is writing fiction,
    not configuration. The value is clamped rather than trusted — a model that draws 250/100
    has lost the plot — and the delta is computed, never believed.
    """
    if not trackers or not reply.strip():
        return 0
    moved = 0
    for match in RENDERED.finditer(reply):
        name = match.group("name").strip().lower()
        tracker = next((t for t in trackers if t.name.lower() == name), None)
        if tracker is None:
            continue
        value = min(max(float(match.group("value")), 0.0), tracker.max)
        if abs(value - tracker.value) < 0.001:
            continue
        tracker.delta = round(value - tracker.value, 2)
        tracker.value = value
        tracker.updated_at_sequence = sequence
        note = match.group("note").strip().strip("—- ")
        if note:
            tracker.note = note[:NOTE_LENGTH]
        moved += 1
    return moved


async def of(session: AsyncSession, story_id: uuid.UUID) -> list[Tracker]:
    """A story's meters, in the order they were added."""
    rows = await session.scalars(
        select(Tracker).where(Tracker.story_id == story_id).order_by(Tracker.created_at, Tracker.id)
    )
    return list(rows)


async def named(session: AsyncSession, story_id: uuid.UUID, name: str) -> Tracker | None:
    return await session.scalar(
        select(Tracker).where(
            Tracker.story_id == story_id, func.lower(Tracker.name) == name.strip().lower()
        )
    )


async def _newest_sequence(session: AsyncSession, story_id: uuid.UUID) -> int | None:
    return await session.scalar(
        select(func.max(Message.sequence)).where(
            Message.story_id == story_id, Message.deleted_at.is_(None)
        )
    )


async def set_value(session: AsyncSession, tracker: Tracker, value: float) -> None:
    """A value set by hand: the delta says what changed, and the note that the reader did it."""
    if not 0 <= value <= tracker.max:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{tracker.name} runs from 0 to {_trim(tracker.max)}.",
        )
    tracker.delta = round(value - tracker.value, 2)
    tracker.value = value
    tracker.note = "set by hand"
    tracker.updated_at_sequence = await _newest_sequence(session, tracker.story_id)


def split_command(argument: str) -> tuple[str, float] | None:
    """`/tracker Trust in Rowan 40` → ("Trust in Rowan", 40.0). The value is the last word, so
    a name of several words needs no quoting. None when the last word is not a number."""
    name, _, last = argument.strip().rpartition(" ")
    if not name.strip():
        return None
    try:
        return name.strip(), float(last)
    except ValueError:
        return None


# --- the API --------------------------------------------------------------------------------------

router = APIRouter(prefix="/stories/{story_id}/trackers", tags=["trackers"])
Session = Annotated[AsyncSession, Depends(get_session)]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Words = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class NewTracker(BaseModel):
    name: Name
    value: float = 0
    max: float = Field(default=100, gt=0)
    means: Words | None = None
    """What it measures, in a line."""
    anchors: Words | None = None
    """What the numbers mean: `0 a stranger, 100 would die for them`."""
    rule: Words | None = None
    """What constrains it: `never moves more than 5 in a turn`."""


class SetTracker(BaseModel):
    value: float | None = None
    max: float | None = Field(default=None, gt=0)
    means: Words | None = None
    anchors: Words | None = None
    rule: Words | None = None


class TrackerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    value: float
    max: float
    delta: float
    note: str | None
    means: str | None
    anchors: str | None
    rule: str | None
    updated_at_sequence: int | None
    """The turn that last moved it; None until one does."""


def _out(tracker: Tracker) -> TrackerOut:
    return TrackerOut.model_validate(tracker)


async def _required(session: AsyncSession, story_id: uuid.UUID, name: str) -> Tracker:
    tracker = await named(session, story_id, name)
    if tracker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"This story has no meter called {name}.")
    return tracker


@router.get("")
async def list_trackers(story_id: uuid.UUID, session: Session) -> list[TrackerOut]:
    await visible_story(session, story_id)
    return [_out(t) for t in await of(session, story_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_tracker(story_id: uuid.UUID, new: NewTracker, session: Session) -> TrackerOut:
    """Adds a meter. It reaches the prompt from the next turn, and the model draws it from then
    on — which is also the warning: a meter the model can see is a meter it writes towards."""
    await visible_story(session, story_id)
    if await named(session, story_id, new.name) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"This story already has a meter called {new.name}."
        )
    if not 0 <= new.value <= new.max:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The value must be between 0 and {_trim(new.max)}.",
        )
    tracker = Tracker(
        story_id=story_id,
        name=new.name,
        value=new.value,
        max=new.max,
        means=new.means,
        anchors=new.anchors,
        rule=new.rule,
    )
    session.add(tracker)
    await session.commit()
    return _out(tracker)


@router.patch("/{name}")
async def change_tracker(
    story_id: uuid.UUID, name: str, change: SetTracker, session: Session
) -> TrackerOut:
    """Sets a meter by hand: its value, its range, or the words that explain it."""
    await visible_story(session, story_id)
    tracker = await _required(session, story_id, name)
    if change.max is not None:
        tracker.max = change.max
        tracker.value = min(tracker.value, change.max)
    if change.value is not None:
        await set_value(session, tracker, change.value)
    for field in ("means", "anchors", "rule"):
        if (words := getattr(change, field)) is not None:
            setattr(tracker, field, words)
    await session.commit()
    return _out(tracker)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tracker(story_id: uuid.UUID, name: str, session: Session) -> None:
    await visible_story(session, story_id)
    await session.delete(await _required(session, story_id, name))
    await session.commit()
