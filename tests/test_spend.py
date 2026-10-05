"""The spend ledger: what the database guarantees about it. What writes to it is tested with
the turn, the reroll and the aside, each of which must leave exactly one row per billed call."""

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Spend, SpendKind, new_id
from tests.factories import a_spend, a_story


async def test_a_row_remembers_what_the_api_reported(session: AsyncSession) -> None:
    story = await a_story(session)
    row = await a_spend(session, story, cost=Decimal("0.0002"))
    await session.commit()

    found = await session.get(Spend, row.id, populate_existing=True)

    assert found is not None
    assert found.kind is SpendKind.REPLY
    assert found.cost == Decimal("0.0002")
    assert isinstance(found.cost, Decimal)
    assert (found.prompt_tokens, found.completion_tokens, found.cached_tokens) == (10, 5, 4)
    assert found.provider == "test-host"
    assert found.generation_id == "gen-1"
    assert found.at is not None


async def test_an_unpriced_call_has_no_cost_rather_than_zero(session: AsyncSession) -> None:
    row = await a_spend(session, await a_story(session), cost=None)

    assert row.cost is None


async def test_the_cost_keeps_every_decimal_place_the_api_sent(session: AsyncSession) -> None:
    """Hundreds of rows of $0.0028 summed in binary floating point drift; in the database they
    add up exactly."""
    story = await a_story(session)
    for _ in range(3):
        await a_spend(session, story, cost=Decimal("0.0000000001"))
    await a_spend(session, story, cost=Decimal("0.0028"))

    total = await session.scalar(select(func.sum(Spend.cost)).where(Spend.story_id == story.id))

    assert total == Decimal("0.0028000003")


async def test_a_row_cannot_be_changed(session: AsyncSession) -> None:
    row = await a_spend(session, await a_story(session))

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(update(Spend).where(Spend.id == row.id).values(cost=Decimal(0)))


async def test_a_row_cannot_be_deleted(session: AsyncSession) -> None:
    row = await a_spend(session, await a_story(session))

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(delete(Spend).where(Spend.id == row.id))


async def test_the_table_cannot_be_truncated(session: AsyncSession) -> None:
    await a_spend(session, await a_story(session))

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(text("TRUNCATE spend"))


async def test_not_even_a_purge_deletes_from_the_ledger(session: AsyncSession) -> None:
    """Erasing a story keeps what it cost: the one door through the messages trigger is shut."""
    row = await a_spend(session, await a_story(session))
    await session.execute(text("SELECT set_config('lustjinn.purging', 'on', true)"))

    with pytest.raises(IntegrityError, match="never changed or deleted"):
        await session.execute(delete(Spend).where(Spend.id == row.id))


async def test_the_ledger_does_not_point_at_the_story_or_the_message(
    session: AsyncSession,
) -> None:
    """No foreign keys, on purpose: a row may outlive both."""
    session.add(Spend(story_id=new_id(), kind=SpendKind.SUMMARY, message_id=new_id()))

    await session.flush()


async def test_a_kind_the_schema_does_not_know_is_refused(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_spend_kind"):
        await session.execute(
            text("INSERT INTO spend (id, story_id, kind) VALUES (:id, :story, 'embedding')"),
            {"id": new_id(), "story": new_id()},
        )
