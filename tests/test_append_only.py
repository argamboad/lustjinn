"""Messages are append-only, and it is the database that says so — not the application."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Message, Role
from tests.factories import a_message, a_story


async def count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Message)) or 0


async def test_deleting_a_message_is_refused(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session))

    with pytest.raises(IntegrityError, match="never deleted"):
        await session.execute(delete(Message).where(Message.id == message.id))


async def test_rewriting_the_text_of_a_message_is_refused(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session), "What was said.")

    with pytest.raises(IntegrityError, match="cannot be changed"):
        await session.execute(
            update(Message).where(Message.id == message.id).values(text="What I wish I had said.")
        )


async def test_changing_who_said_it_is_refused(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session), role=Role.USER)

    with pytest.raises(IntegrityError, match="cannot be changed"):
        await session.execute(
            update(Message).where(Message.id == message.id).values(role=Role.ASSISTANT)
        )


async def test_moving_a_message_to_another_story_is_refused(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session))
    elsewhere = await a_story(session)

    with pytest.raises(IntegrityError, match="cannot be changed"):
        await session.execute(
            update(Message).where(Message.id == message.id).values(story_id=elsewhere.id)
        )


async def test_renumbering_a_message_is_refused(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session))

    with pytest.raises(IntegrityError, match="cannot be changed"):
        await session.execute(update(Message).where(Message.id == message.id).values(sequence=7))


async def test_the_ordinary_way_of_editing_an_object_is_refused_too(session: AsyncSession) -> None:
    """Not only hand-written SQL: changing the attribute and saving runs into the same wall."""
    message = await a_message(session, await a_story(session))
    message.text = "Rewritten."

    with pytest.raises(IntegrityError, match="cannot be changed"):
        await session.flush()


async def test_hiding_a_message_is_allowed_and_keeps_the_row(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session), "Still here.")

    message.deleted_at = datetime.now(UTC)
    await session.commit()

    found = await session.get(Message, message.id, populate_existing=True)
    assert found is not None
    assert found.deleted_at is not None
    assert found.text == "Still here."


async def test_clearing_the_request_hash_is_allowed(session: AsyncSession) -> None:
    """A retry of a hidden turn needs this (step 3): the hash is bookkeeping, not the turn."""
    message = await a_message(session, await a_story(session), request_hash="A1B2")

    message.request_hash = None
    await session.commit()

    found = await session.get(Message, message.id, populate_existing=True)
    assert found is not None
    assert found.request_hash is None


async def test_saving_a_message_unchanged_is_not_an_edit(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session), "The same.")

    await session.execute(update(Message).where(Message.id == message.id).values(text="The same."))


async def test_emptying_the_table_is_refused(session: AsyncSession) -> None:
    await a_message(session, await a_story(session))

    # CASCADE, because embeddings point at messages and Postgres refuses the plain form for that
    # reason alone; the trigger must be what says no.
    with pytest.raises(IntegrityError, match="cannot be truncated"):
        await session.execute(text("TRUNCATE messages CASCADE"))


async def test_a_purge_that_announces_itself_may_delete(session: AsyncSession) -> None:
    await a_message(session, await a_story(session))
    assert await count(session) == 1

    # What SET LOCAL does, as a function call: on for this transaction only.
    await session.execute(text("SELECT set_config('lustjinn.purging', 'on', true)"))
    await session.execute(delete(Message))

    assert await count(session) == 0


async def test_even_a_purge_cannot_rewrite_a_message(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session))
    await session.execute(text("SELECT set_config('lustjinn.purging', 'on', true)"))

    with pytest.raises(IntegrityError, match="cannot be changed"):
        await session.execute(
            update(Message).where(Message.id == message.id).values(text="Rewritten.")
        )


async def test_the_guard_is_back_once_the_purge_is_over(session: AsyncSession) -> None:
    message = await a_message(session, await a_story(session))
    await session.execute(text("SELECT set_config('lustjinn.purging', 'on', true)"))
    await session.execute(text("SELECT set_config('lustjinn.purging', 'off', true)"))

    with pytest.raises(IntegrityError, match="never deleted"):
        await session.execute(delete(Message).where(Message.id == message.id))
