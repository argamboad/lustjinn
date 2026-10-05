"""Shortcuts that put rows in the database for a test, with sensible defaults."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import (
    Character,
    Message,
    Persona,
    Role,
    Snippet,
    Spend,
    SpendKind,
    Story,
)


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


async def a_snippet(
    session: AsyncSession, name: str = "storm", text: str = "Rain hammers the glass."
) -> Snippet:
    snippet = Snippet(name=name, text=text)
    session.add(snippet)
    await session.flush()
    return snippet


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


async def a_spend(
    session: AsyncSession,
    story: Story,
    kind: SpendKind = SpendKind.REPLY,
    cost: Decimal | None = Decimal("0.0002"),
    message_id: uuid.UUID | None = None,
) -> Spend:
    """A ledger row as the scripted model's default reply would leave it."""
    row = Spend(
        story_id=story.id,
        kind=kind,
        message_id=message_id,
        model="test-model",
        provider="test-host",
        generation_id="gen-1",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=4,
        cost=cost,
    )
    session.add(row)
    await session.flush()
    return row
