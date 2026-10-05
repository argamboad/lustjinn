"""What the database itself guarantees about stories and messages."""

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from lustjinn.models import Base, Character, Message, Role, Story, new_id
from tests.conftest import migrate
from tests.factories import a_character, a_message, a_persona, a_story


async def test_the_migrations_build_exactly_what_the_models_describe(engine: AsyncEngine) -> None:
    def differences(connection: Connection) -> list[Any]:
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)

    async with engine.connect() as connection:
        assert await connection.run_sync(differences) == []


async def test_the_migrations_can_be_undone_and_applied_again(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "base")
        assert await connection.scalar(text("SELECT to_regclass('messages')")) is None
        await connection.run_sync(migrate, "head")
        assert await connection.scalar(text("SELECT to_regclass('messages')")) is not None


def test_ids_sort_by_the_time_they_were_made() -> None:
    first, second, third = new_id(), new_id(), new_id()

    assert first < second < third


async def test_a_story_keeps_its_character_and_persona(session: AsyncSession) -> None:
    character = await a_character(session)
    persona = await a_persona(session)
    story = Story(name="Vardhal", character_id=character.id, persona_id=persona.id)
    session.add(story)
    await session.commit()

    found = await session.scalar(select(Story).where(Story.id == story.id))

    assert found is not None
    assert (found.character_id, found.persona_id) == (character.id, persona.id)
    assert found.model is None
    assert found.deleted_at is None
    assert found.created_at is not None


async def test_a_story_needs_a_character_that_exists(session: AsyncSession) -> None:
    session.add(Story(name="Nowhere", character_id=new_id()))

    with pytest.raises(IntegrityError, match="fk_stories_character_id_characters"):
        await session.flush()


async def test_a_character_a_story_uses_cannot_be_deleted(session: AsyncSession) -> None:
    character = await a_character(session)
    await a_story(session, character)

    with pytest.raises(IntegrityError, match="fk_stories_character_id_characters"):
        await session.execute(delete(Character).where(Character.id == character.id))


async def test_a_character_no_story_uses_can_be_deleted(session: AsyncSession) -> None:
    character = await a_character(session)

    await session.execute(delete(Character).where(Character.id == character.id))

    assert await session.get(Character, character.id) is None


async def test_two_characters_cannot_share_a_name_whatever_the_case(session: AsyncSession) -> None:
    await a_character(session, name="Elena")

    with pytest.raises(IntegrityError, match="uq_characters_name_lower"):
        await a_character(session, name="ELENA")


async def test_two_personas_cannot_share_a_name_whatever_the_case(session: AsyncSession) -> None:
    await a_persona(session, name="Traveller")

    with pytest.raises(IntegrityError, match="uq_personas_name_lower"):
        await a_persona(session, name="traveller")


async def test_messages_come_back_in_the_order_of_their_sequence(session: AsyncSession) -> None:
    story = await a_story(session)
    for words in ("One.", "Two.", "Three."):
        await a_message(session, story, words)

    texts = await session.scalars(
        select(Message.text).where(Message.story_id == story.id).order_by(Message.sequence)
    )

    assert list(texts) == ["One.", "Two.", "Three."]


async def test_a_sequence_number_cannot_be_reused_within_a_story(session: AsyncSession) -> None:
    story = await a_story(session)
    await a_message(session, story)
    session.add(Message(story_id=story.id, sequence=1, role=Role.ASSISTANT, text="Again."))

    with pytest.raises(IntegrityError, match="uq_messages_story_sequence"):
        await session.flush()


async def test_the_same_sequence_number_in_another_story_is_fine(session: AsyncSession) -> None:
    await a_message(session, await a_story(session))
    await a_message(session, await a_story(session))


async def test_a_sequence_number_starts_at_one(session: AsyncSession) -> None:
    story = await a_story(session)
    session.add(Message(story_id=story.id, sequence=0, role=Role.USER, text="Before the start."))

    with pytest.raises(IntegrityError, match="ck_messages_sequence_positive"):
        await session.flush()


async def test_the_same_request_hash_cannot_land_twice_in_one_story(session: AsyncSession) -> None:
    story = await a_story(session)
    await a_message(session, story, request_hash="A1B2")

    with pytest.raises(IntegrityError, match="uq_messages_story_request_hash"):
        await a_message(session, story, request_hash="A1B2")


async def test_the_same_request_hash_in_a_different_story_is_fine(session: AsyncSession) -> None:
    await a_message(session, await a_story(session), request_hash="A1B2")
    await a_message(session, await a_story(session), request_hash="A1B2")


async def test_messages_without_a_hash_do_not_collide(session: AsyncSession) -> None:
    story = await a_story(session)

    await a_message(session, story)
    await a_message(session, story)


async def test_a_role_the_schema_does_not_know_is_refused(session: AsyncSession) -> None:
    story = await a_story(session)

    with pytest.raises(IntegrityError, match="ck_messages_role"):
        await session.execute(
            text(
                "INSERT INTO messages (id, story_id, sequence, role, text) "
                "VALUES (:id, :story, 1, 'narrator', 'Hm.')"
            ),
            {"id": new_id(), "story": story.id},
        )


async def test_a_message_remembers_who_wrote_it(session: AsyncSession) -> None:
    story = await a_story(session)
    message = await a_message(session, story, role=Role.ASSISTANT)
    await session.commit()

    found = await session.get(Message, message.id, populate_existing=True)

    assert found is not None
    assert found.role is Role.ASSISTANT
    assert found.model is None  # nobody's model: a person wrote this one
    assert found.sent_at is not None
