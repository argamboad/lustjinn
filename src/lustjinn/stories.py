"""The stories API: what both clients open on."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from lustjinn.deps import Session
from lustjinn.models import Character, Message, Persona, Role, Story

router = APIRouter(prefix="/stories", tags=["stories"])


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

PREVIEW_LENGTH = 200


class NewStory(BaseModel):
    name: Name
    character_id: uuid.UUID
    persona_id: uuid.UUID | None = None


class Rename(BaseModel):
    name: Name


class StoryOut(BaseModel):
    # Read off a row of `_stories()`, whose columns are labelled with these names.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    character_id: uuid.UUID
    character_name: str
    persona_id: uuid.UUID | None
    persona_name: str | None
    created_at: datetime
    last_message_at: datetime | None
    """When the newest visible message was sent; None for a story with no messages yet."""
    last_message_preview: str | None
    """The start of that message, for a list that shows the latest line under each name."""


class MessageOut(BaseModel):
    # from_attributes: build this from a Message object by reading the attributes of the same name.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    role: Role
    text: str
    model: str | None
    provider: str | None
    sent_at: datetime


class StoryWithMessages(StoryOut):
    messages: list[MessageOut]


def _stories(story_id: uuid.UUID | None = None):
    """Visible stories with their character, persona and newest visible message, one row per
    story with a column for each field of `StoryOut` — so a row validates as one.

    Newest activity first. One story when `story_id` is given.
    """
    # LATERAL: a subquery that runs once per story and may refer to that story's row.
    newest = (
        select(Message.sent_at, Message.text)
        .where(Message.story_id == Story.id, Message.deleted_at.is_(None))
        .order_by(Message.sequence.desc())
        .limit(1)
        .lateral("newest")
    )
    query = (
        select(
            Story.id,
            Story.name,
            Story.character_id,
            Character.name.label("character_name"),
            Story.persona_id,
            Persona.name.label("persona_name"),
            Story.created_at,
            newest.c.sent_at.label("last_message_at"),
            # The preview is cut in the database: only its first characters leave it.
            func.left(newest.c.text, PREVIEW_LENGTH).label("last_message_preview"),
        )
        .join(Character, Story.character_id == Character.id)
        .outerjoin(Persona, Story.persona_id == Persona.id)
        .outerjoin(newest, true())
        .where(Story.deleted_at.is_(None))
        .order_by(func.coalesce(newest.c.sent_at, Story.created_at).desc(), Story.id.desc())
    )
    if story_id is not None:
        query = query.where(Story.id == story_id)
    return query


async def _one(session: AsyncSession, story_id: uuid.UUID) -> StoryOut:
    row = (await session.execute(_stories(story_id))).one_or_none()
    if row is None:
        # A deleted story answers exactly like one that never existed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no story with that id.")
    return StoryOut.model_validate(row)


async def visible_story(session: AsyncSession, story_id: uuid.UUID) -> Story:
    """The story, or a 404 that does not say whether it was deleted or never existed."""
    story = await session.scalar(
        select(Story).where(Story.id == story_id, Story.deleted_at.is_(None))
    )
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no story with that id.")
    return story


async def playable_story(session: AsyncSession, story_id: uuid.UUID) -> Story:
    """A visible story with its character and persona loaded: what a prompt is built from."""
    story = await session.scalar(
        select(Story)
        .options(joinedload(Story.character), joinedload(Story.persona))
        .where(Story.id == story_id, Story.deleted_at.is_(None))
    )
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no story with that id.")
    return story


async def visible_messages(session: AsyncSession, story_id: uuid.UUID) -> list[Message]:
    """The story's transcript as the reader sees it: hidden turns left out, in order."""
    rows = await session.scalars(
        select(Message)
        .where(Message.story_id == story_id, Message.deleted_at.is_(None))
        .order_by(Message.sequence)
    )
    return list(rows)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_story(new: NewStory, session: Session) -> StoryWithMessages:
    """Starts a story. If the character has an opening, it becomes the story's first message."""
    character = await session.get(Character, new.character_id)
    if character is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "There is no character with that id."
        )
    if new.persona_id is not None and await session.get(Persona, new.persona_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "There is no persona with that id."
        )
    story = Story(name=new.name, character_id=character.id, persona_id=new.persona_id)
    session.add(story)
    if character.opening:
        # Written by a person, so no model: that is how a reroll later knows to leave it alone.
        session.add(Message(story=story, sequence=1, role=Role.ASSISTANT, text=character.opening))
    await session.commit()
    return await read_story(story.id, session)


@router.get("")
async def list_stories(session: Session) -> list[StoryOut]:
    """Every story that has not been deleted, the one played most recently first."""
    rows = await session.execute(_stories())
    return [StoryOut.model_validate(row) for row in rows]


@router.get("/{story_id}")
async def read_story(story_id: uuid.UUID, session: Session) -> StoryWithMessages:
    """One story with its visible messages, in order."""
    story = await _one(session, story_id)
    messages = await session.scalars(
        select(Message)
        .where(Message.story_id == story_id, Message.deleted_at.is_(None))
        .order_by(Message.sequence)
    )
    return StoryWithMessages(
        **story.model_dump(), messages=[MessageOut.model_validate(m) for m in messages]
    )


@router.patch("/{story_id}")
async def rename_story(story_id: uuid.UUID, rename: Rename, session: Session) -> StoryOut:
    story = await visible_story(session, story_id)
    story.name = rename.name
    await session.commit()
    return await _one(session, story_id)


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(story_id: uuid.UUID, session: Session) -> None:
    """Hides the story. Its rows stay; erasing them for good is a separate, deliberate act."""
    story = await visible_story(session, story_id)
    story.deleted_at = datetime.now(UTC)
    await session.commit()
