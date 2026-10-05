"""The library: characters, personas and snippets, on three shelves behind one set of endpoints.

A story points at its character and persona by id, so editing either reaches every story from
its next turn, and renaming is free. Deleting one a live story uses is refused — by the
database, with a foreign key, and before that by this code, which can say which stories. A
persona set as the default counts as used by every story that names none.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm.exc import StaleDataError

from lustjinn.db import get_session
from lustjinn.models import (
    AppSettings,
    Character,
    LibraryEntry,
    LibraryHistory,
    LibraryKind,
    Persona,
    Snippet,
    Story,
)

router = APIRouter(prefix="/library", tags=["library"])
Session = Annotated[AsyncSession, Depends(get_session)]

PREVIEW_LENGTH = 200
Slug = Literal["characters", "personas", "snippets"]

# Characters no name may contain, on any shelf: the set Windows refuses in a file name. A name
# may become one when a story is exported (step 7), and being refused a colon is a smaller
# surprise than an export that only works on one machine.
RESERVED_IN_NAMES = set('<>:"/\\|?*')
# A snippet is typed as `:name`, so its name must be typeable as one word.
SNIPPET_NAME = re.compile(r"^[A-Za-z0-9_+-]{1,32}$")


@dataclass(frozen=True)
class Shelf[E: LibraryEntry]:
    """One shelf: which table, what one entry on it is called, and where its text lives."""

    slug: Slug
    kind: str
    model: type[E]
    text_of: Callable[[E], str]
    set_text: Callable[[E, str], None]


def _card(character: Character) -> str:
    return character.card


def _set_card(character: Character, text: str) -> None:
    character.card = text


def _text(entry: Persona | Snippet) -> str:
    return entry.text


def _set_text(entry: Persona | Snippet, text: str) -> None:
    entry.text = text


SHELVES: dict[str, Shelf[Any]] = {
    "characters": Shelf("characters", "character", Character, _card, _set_card),
    "personas": Shelf("personas", "persona", Persona, _text, _set_text),
    "snippets": Shelf("snippets", "snippet", Snippet, _text, _set_text),
}


def shelf_named(shelf: Slug) -> Shelf[Any]:
    """The shelf a path names. The `Slug` type on the path parameter already refused others."""
    return SHELVES[shelf]


OnShelf = Annotated[Shelf[Any], Depends(shelf_named)]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(min_length=1)]


def _check_name(name: str) -> str:
    if RESERVED_IN_NAMES & set(name) or any(c.isprintable() is False for c in name):
        raise ValueError('a name cannot contain any of < > : " / \\ | ? * or control characters')
    return name


class NewEntry(BaseModel):
    name: Name
    text: Body
    opening: str | None = None
    """Characters only: the scene a story starts on. Blank is the same as none."""

    @field_validator("name")
    @classmethod
    def _usable(cls, name: str) -> str:
        return _check_name(name)


class EntryChanges(BaseModel):
    """What a save may change. Only the fields given are touched."""

    version: int
    """The version the editor started from. A save over a newer one is refused: a save made on
    a phone must not quietly undo an edit made on the laptop in between."""
    name: Name | None = None
    text: Body | None = None
    opening: str | None = None

    @field_validator("name")
    @classmethod
    def _usable(cls, name: str | None) -> str | None:
        return None if name is None else _check_name(name)


class EntrySummary(BaseModel):
    id: uuid.UUID
    name: str
    hidden: bool
    """A name starting with `_` is kept but not listed by default: working papers, a template,
    notes towards a character. Anything that names it still finds it."""
    version: int
    updated_at: datetime
    preview: str


class EntryOut(EntrySummary):
    text: str
    opening: str | None
    """Characters only; None on the other shelves."""
    used_by: list[str]
    """The live stories that use the entry, by name. Empty for a snippet: it is copied into a
    message when used and never read again."""


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    name: str
    text: str
    opening: str | None
    saved_at: datetime


class Defaults(BaseModel):
    default_persona_id: uuid.UUID | None
    default_persona_name: str | None


class SetDefaults(BaseModel):
    default_persona_id: uuid.UUID | None


def _summary(shelf: Shelf[Any], entry: LibraryEntry) -> EntrySummary:
    return EntrySummary(
        id=entry.id,
        name=entry.name,
        hidden=entry.name.startswith("_"),
        version=entry.version,
        updated_at=entry.updated_at,
        preview=shelf.text_of(entry)[:PREVIEW_LENGTH],
    )


def _out(shelf: Shelf[Any], entry: LibraryEntry, used_by: Sequence[str]) -> EntryOut:
    return EntryOut(
        **_summary(shelf, entry).model_dump(),
        text=shelf.text_of(entry),
        opening=entry.opening if isinstance(entry, Character) else None,
        used_by=list(used_by),
    )


async def _settings(session: AsyncSession) -> AppSettings | None:
    return await session.get(AppSettings, 1)


async def default_persona(session: AsyncSession) -> Persona | None:
    """The persona a story plays as when it names none, if one is set."""
    found = await _settings(session)
    if found is None or found.default_persona_id is None:
        return None
    return await session.get(Persona, found.default_persona_id)


async def _one(session: AsyncSession, shelf: Shelf[Any], entry_id: uuid.UUID) -> LibraryEntry:
    entry = await session.get(shelf.model, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"There is no {shelf.kind} with that id.")
    return entry


async def _taken(
    session: AsyncSession, shelf: Shelf[Any], name: str, but: uuid.UUID | None = None
) -> bool:
    """Whether another entry on the shelf has this name, in any case."""
    query = select(shelf.model.id).where(func.lower(shelf.model.name) == name.lower())
    if but is not None:
        query = query.where(shelf.model.id != but)
    return await session.scalar(query) is not None


async def used_by(session: AsyncSession, shelf: Shelf[Any], entry: LibraryEntry) -> list[str]:
    """The live stories that use the entry, alphabetically. A snippet is used by none."""
    if isinstance(entry, Character):
        condition = Story.character_id == entry.id
    elif isinstance(entry, Persona):
        condition = Story.persona_id == entry.id
        # The default persona is also used by every story that names none: deleting it would
        # leave those with nobody to play as, just as surely as deleting one a story names.
        settings = await _settings(session)
        if settings is not None and settings.default_persona_id == entry.id:
            condition = condition | Story.persona_id.is_(None)
    else:
        return []
    names = await session.scalars(
        select(Story.name)
        .where(condition, Story.deleted_at.is_(None))
        .order_by(alphabetical(Story.name))
    )
    return list(names)


def alphabetical(name: InstrumentedAttribute[str]) -> ColumnElement[str]:
    """The order a reader expects, the same on every server.

    Left to itself, Postgres sorts by the collation its database was created with, and those
    disagree: one ignores a leading underscore, another puts accented letters after `z`.
    `und-x-icu` is ICU's language-neutral order — punctuation, digits, then letters without
    regard to case, accents beside their base letter.
    """
    return name.collate("und-x-icu")


def _opening(given: str | None) -> str | None:
    """Blank is none: an opening is a page, or it is not there."""
    return given if given and given.strip() else None


def _remembered(shelf: Shelf[Any], entry: LibraryEntry, version: int) -> LibraryHistory:
    """The history row for a version about to be saved."""
    return LibraryHistory(
        kind=LibraryKind(shelf.kind),
        entry_id=entry.id,
        version=version,
        name=entry.name,
        text=shelf.text_of(entry),
        opening=entry.opening if isinstance(entry, Character) else None,
    )


def _changed_elsewhere(shelf: Shelf[Any], current: LibraryEntry) -> HTTPException:
    """A 409 that carries the entry as it is now, so a client can show both texts and let the
    reader decide, instead of losing either."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "message": f"This {shelf.kind} changed somewhere else since you opened it. Nothing "
            "was saved. Here is what it says now; save again to replace it.",
            "current": _out(shelf, current, []).model_dump(mode="json"),
        },
    )


@router.get("/settings")
async def read_defaults(session: Session) -> Defaults:
    persona = await default_persona(session)
    return Defaults(
        default_persona_id=None if persona is None else persona.id,
        default_persona_name=None if persona is None else persona.name,
    )


@router.put("/settings")
async def set_defaults(body: SetDefaults, session: Session) -> Defaults:
    """Names the default persona, or clears it with null."""
    if (
        body.default_persona_id is not None
        and await session.get(Persona, body.default_persona_id) is None
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "There is no persona with that id."
        )
    settings = await _settings(session)
    if settings is None:
        settings = AppSettings()
        session.add(settings)
    settings.default_persona_id = body.default_persona_id
    await session.commit()
    return await read_defaults(session)


@router.get("/{shelf}")
async def list_entries(
    shelf: OnShelf, session: Session, hidden: bool = False
) -> list[EntrySummary]:
    """The shelf, alphabetically. Names starting with `_` only when `hidden` is asked for."""
    query = select(shelf.model).order_by(alphabetical(shelf.model.name))
    if not hidden:
        # autoescape: `_` is a wildcard in LIKE, which `startswith` compiles to.
        query = query.where(~shelf.model.name.startswith("_", autoescape=True))
    return [_summary(shelf, entry) for entry in await session.scalars(query)]


@router.post("/{shelf}", status_code=status.HTTP_201_CREATED)
async def create_entry(shelf: OnShelf, new: NewEntry, session: Session) -> EntryOut:
    """Adds an entry. A name already on the shelf, in any case, is refused: create never
    becomes replace."""
    if shelf.slug == "snippets" and not SNIPPET_NAME.match(new.name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A snippet's name is typed as :name, so it is 1 to 32 of letters, digits, _ + -.",
        )
    if shelf.slug != "characters" and new.opening is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"A {shelf.kind} has no opening."
        )
    if await _taken(session, shelf, new.name):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A {shelf.kind} called '{new.name}' already exists. Edit it, or pick another name.",
        )
    entry: LibraryEntry = shelf.model(name=new.name)
    shelf.set_text(entry, new.text)
    if isinstance(entry, Character):
        entry.opening = _opening(new.opening)
    session.add(entry)
    await session.flush()  # gives it its id, for the history row
    session.add(_remembered(shelf, entry, version=1))
    await session.commit()
    # The database filled in updated_at; read it back, explicitly, since a lazy load is not
    # something async code can do by itself.
    await session.refresh(entry)
    return _out(shelf, entry, [])


@router.get("/{shelf}/{entry_id}")
async def read_entry(shelf: OnShelf, entry_id: uuid.UUID, session: Session) -> EntryOut:
    entry = await _one(session, shelf, entry_id)
    return _out(shelf, entry, await used_by(session, shelf, entry))


@router.patch("/{shelf}/{entry_id}")
async def save_entry(
    shelf: OnShelf, entry_id: uuid.UUID, changes: EntryChanges, session: Session
) -> EntryOut:
    """Saves what was given: a new name, a new text, a new opening. Renaming is free — stories
    hold the id — and reaches every story from its next turn, as does the text.

    Refused with 409 when the entry has moved past the version the editor started from. A save
    that changes nothing writes nothing: the version stays, and no history row is added.
    """
    entry = await _one(session, shelf, entry_id)
    if changes.version != entry.version:
        raise _changed_elsewhere(shelf, entry)
    if changes.name is not None and changes.name != entry.name:
        if shelf.slug == "snippets" and not SNIPPET_NAME.match(changes.name):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A snippet's name is typed as :name, so it is 1 to 32 of letters, digits, _ + -.",
            )
        if await _taken(session, shelf, changes.name, but=entry.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A {shelf.kind} called '{changes.name}' already exists.",
            )
        entry.name = changes.name
    if changes.text is not None:
        shelf.set_text(entry, changes.text)
    if "opening" in changes.model_fields_set:
        if not isinstance(entry, Character):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"A {shelf.kind} has no opening."
            )
        entry.opening = _opening(changes.opening)
    if session.is_modified(entry):
        session.add(_remembered(shelf, entry, version=entry.version + 1))
        try:
            await session.commit()
        except StaleDataError:
            # Loaded a moment ago and already gone: another save landed between our read and
            # our write. The ORM's own WHERE version = … caught it; the client gets the same
            # answer as a stale version would.
            await session.rollback()
            raise _changed_elsewhere(shelf, await _one(session, shelf, entry_id)) from None
        await session.refresh(entry)
    return _out(shelf, entry, await used_by(session, shelf, entry))


@router.get("/{shelf}/{entry_id}/history")
async def read_history(shelf: OnShelf, entry_id: uuid.UUID, session: Session) -> list[HistoryOut]:
    """Every version ever saved, newest first. Still there after the entry is deleted."""
    rows = await session.scalars(
        select(LibraryHistory)
        .where(LibraryHistory.kind == LibraryKind(shelf.kind), LibraryHistory.entry_id == entry_id)
        .order_by(LibraryHistory.version.desc())
    )
    found = [HistoryOut.model_validate(row) for row in rows]
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"There is no {shelf.kind} with that id.")
    return found


@router.delete("/{shelf}/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(shelf: OnShelf, entry_id: uuid.UUID, session: Session) -> None:
    """Removes an entry no live story uses. Asked at the moment of deleting, not trusted from
    when a screen was drawn: a story could have been started with it in between."""
    entry = await _one(session, shelf, entry_id)
    users = await used_by(session, shelf, entry)
    if users:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This {shelf.kind} is used by {', '.join(users)}. It stays until they do not.",
        )
    await session.delete(entry)
    try:
        await session.commit()
    except IntegrityError:
        # No live story uses it, but a deleted one still points at it, and the foreign key
        # does not know the difference. Erasing deleted stories for good is step 7.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A deleted story still refers to this {shelf.kind}. It can go once that story is "
            "erased for good.",
        ) from None
