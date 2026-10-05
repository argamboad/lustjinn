"""Puts the dummy character and persona in the database, so there is something to play with.

    uv run python scripts/seed_dummy.py

The text is the test fixture under tests/fixtures/dummy/: a fictional character of realistic
size, written for this project. Safe to run twice — an entry that already exists is left alone.
Delete both when the real library is in; a character a story still uses cannot be deleted, so
its stories go first.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.db import dispose_engine, get_sessionmaker
from lustjinn.models import Character, Persona

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "dummy"
CHARACTER_NAME = "The Gilded Heron"
PERSONA_NAME = "Rowan Hale"


@dataclass(frozen=True)
class Dummy:
    character_name: str
    card: str
    opening: str
    persona_name: str
    persona: str


def load() -> Dummy:
    """Reads the fixture files. Line endings come out as `\\n` whatever the checkout used."""

    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8").strip() + "\n"

    return Dummy(
        character_name=CHARACTER_NAME,
        card=read("character.txt"),
        opening=read("opening.txt"),
        persona_name=PERSONA_NAME,
        persona=read("persona.txt"),
    )


async def seed(session: AsyncSession) -> tuple[Character, Persona]:
    """Adds the character and the persona unless one of that name is already there."""
    dummy = load()

    character = await session.scalar(
        select(Character).where(func.lower(Character.name) == dummy.character_name.lower())
    )
    if character is None:
        character = Character(name=dummy.character_name, card=dummy.card, opening=dummy.opening)
        session.add(character)

    persona = await session.scalar(
        select(Persona).where(func.lower(Persona.name) == dummy.persona_name.lower())
    )
    if persona is None:
        persona = Persona(name=dummy.persona_name, text=dummy.persona)
        session.add(persona)

    await session.flush()
    return character, persona


async def main() -> None:
    async with get_sessionmaker()() as session:
        character, persona = await seed(session)
        await session.commit()
    await dispose_engine()
    print(f"character  {character.name}  {character.id}")
    print(f"persona    {persona.name}  {persona.id}")


if __name__ == "__main__":
    asyncio.run(main())
