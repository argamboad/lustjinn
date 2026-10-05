"""The dummy character: a card of realistic size for tests, and a seeded row to play with."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Character, Persona
from scripts.seed_dummy import Dummy, seed


def words(text: str) -> int:
    return len(text.split())


def test_the_card_is_the_size_of_a_real_one(dummy: Dummy) -> None:
    """A four-word card hid a bug in airp that cost a story twenty-four turns of memory."""
    assert 1500 <= words(dummy.card) <= 4000


def test_the_card_has_the_sections_a_card_is_built_from(dummy: Dummy) -> None:
    for section in ("=== THE WORLD ===", "=== WHO PLAYS WHOM ===", "=== THE CHARACTERS ==="):
        assert section in dummy.card
    assert "You never write or act for: the user." in dummy.card


def test_the_card_says_everyone_in_it_is_an_adult(dummy: Dummy) -> None:
    assert "Every character in this story is an adult." in dummy.card


def test_the_opening_and_the_persona_are_there(dummy: Dummy) -> None:
    assert words(dummy.opening) > 100
    assert words(dummy.persona) > 150
    assert dummy.persona.startswith("Rowan Hale.")


def test_the_text_has_no_windows_line_endings(dummy: Dummy) -> None:
    assert "\r" not in dummy.card + dummy.opening + dummy.persona


async def test_seeding_adds_the_character_with_its_opening_and_the_persona(
    session: AsyncSession, dummy: Dummy
) -> None:
    character, persona = await seed(session)
    await session.commit()

    assert (character.name, character.card, character.opening) == (
        "The Gilded Heron",
        dummy.card,
        dummy.opening,
    )
    assert (persona.name, persona.text) == ("Rowan Hale", dummy.persona)
    assert character.version == 1


async def test_seeding_twice_adds_nothing(session: AsyncSession) -> None:
    first = await seed(session)
    second = await seed(session)

    assert [row.id for row in first] == [row.id for row in second]
    assert await session.scalar(select(func.count()).select_from(Character)) == 1
    assert await session.scalar(select(func.count()).select_from(Persona)) == 1
