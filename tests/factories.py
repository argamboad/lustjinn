"""Shortcuts that put rows in the database for a test, with sensible defaults."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Character, Message, Persona, Role, Story


async def a_character(
    session: AsyncSession, name: str | None = None, opening: str | None = None
) -> Character:
    character = Character(
        name=name or f"Elena {uuid.uuid4().hex[:8]}", card="You are Elena.", opening=opening
    )
    session.add(character)
    await session.flush()
    return character


async def a_persona(session: AsyncSession, name: str | None = None) -> Persona:
    persona = Persona(name=name or f"Traveller {uuid.uuid4().hex[:8]}", text="A traveller.")
    session.add(persona)
    await session.flush()
    return persona


async def a_story(
    session: AsyncSession, character: Character | None = None, name: str = "Vardhal"
) -> Story:
    character = character or await a_character(session)
    story = Story(name=name, character_id=character.id)
    session.add(story)
    await session.flush()
    return story


async def a_message(
    session: AsyncSession,
    story: Story,
    text: str = "Hello.",
    role: Role = Role.USER,
    request_hash: str | None = None,
) -> Message:
    """Appends a message at the story's next sequence number."""
    last = await session.scalar(
        select(func.max(Message.sequence)).where(Message.story_id == story.id)
    )
    message = Message(
        story_id=story.id,
        sequence=(last or 0) + 1,
        role=role,
        text=text,
        request_hash=request_hash,
    )
    session.add(message)
    await session.flush()
    return message
