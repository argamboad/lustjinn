"""Cost reports: sums over the ledger, read at report time, matched against hand-made totals."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.models import Role, Spend, SpendKind, Story
from lustjinn.spend import NOTE, PURGED
from tests.factories import a_character, a_message, a_story

MARCH = datetime(2026, 3, 10, 12, tzinfo=UTC)
APRIL = datetime(2026, 4, 2, 9, tzinfo=UTC)


def a_row(
    story_id: uuid.UUID,
    kind: SpendKind = SpendKind.REPLY,
    *,
    cost: Decimal | None = Decimal("0.0010"),
    at: datetime = MARCH,
    message_id: uuid.UUID | None = None,
    provider: str | None = "DeepInfra",
    prompt: int = 1000,
    cached: int = 400,
    completion: int = 100,
) -> Spend:
    return Spend(
        story_id=story_id,
        kind=kind,
        message_id=message_id,
        model="m",
        provider=provider,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        cost=cost,
        at=at,
    )


async def a_ledger(session: AsyncSession) -> tuple[Story, Story]:
    """Two stories and a purged one. Story A: three replies (one rerolled away, one unpriced),
    a question, a summary and an extraction, all in March; story B: one reply in April; the
    purged story: one row in March with no story behind it."""
    character = await a_character(session)
    a = await a_story(session, character, name="Alpha")
    b = await a_story(session, character, name="Beta")
    kept = await a_message(session, a, "Kept.", Role.ASSISTANT)
    gone = await a_message(session, a, "Rerolled away.", Role.ASSISTANT)
    gone.deleted_at = datetime.now(UTC)
    session.add_all(
        [
            a_row(a.id, message_id=kept.id, cost=Decimal("0.0010")),
            a_row(a.id, message_id=gone.id, cost=Decimal("0.0020"), at=MARCH + timedelta(hours=1)),
            a_row(a.id, cost=None, provider=None, cached=0, at=MARCH + timedelta(hours=2)),
            a_row(a.id, SpendKind.ASIDE, cost=Decimal("0.0003"), completion=50),
            a_row(a.id, SpendKind.SUMMARY, cost=Decimal("0.0005"), provider="Other", cached=0),
            a_row(a.id, SpendKind.FACTS, cost=Decimal("0.0004"), provider="Other", cached=0),
            a_row(b.id, cost=Decimal("0.0100"), at=APRIL),
            a_row(uuid.uuid4(), cost=Decimal("0.0007"), at=MARCH + timedelta(days=1)),
        ]
    )
    await session.commit()
    return a, b


async def test_the_whole_report_matches_hand_made_totals(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    await a_ledger(session)

    response = await client.get("/spend")

    assert response.status_code == 200
    report = response.json()
    assert report["calls"] == 8
    assert Decimal(report["cost"]) == Decimal("0.0149")  # the unpriced call adds nothing
    assert report["unpriced"] == 1
    assert (report["discarded_calls"], Decimal(report["discarded_cost"])) == (1, Decimal("0.0020"))
    assert report["prompt_tokens"] == 8000
    assert report["completion_tokens"] == 750
    assert report["cached_tokens"] == 400 * 5
    assert report["cached_share"] == 0.25
    assert report["note"] == NOTE
    kinds = {k["kind"]: k for k in report["by_kind"]}
    assert kinds["reply"]["calls"] == 5
    assert Decimal(kinds["reply"]["cost"]) == Decimal("0.0137")
    assert kinds["reply"]["unpriced"] == 1
    assert [k["kind"] for k in report["by_kind"]] == ["aside", "facts", "reply", "summary"]


async def test_stories_are_listed_dearest_first_and_a_purged_one_by_that_name(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    a, b = await a_ledger(session)

    report = (await client.get("/spend")).json()

    names = [s["name"] for s in report["by_story"]]
    assert names == ["Beta", "Alpha", PURGED]
    alpha = report["by_story"][1]
    assert alpha["story_id"] == str(a.id)
    assert alpha["calls"] == 6
    assert Decimal(alpha["cost"]) == Decimal("0.0042")
    assert (alpha["discarded_calls"], Decimal(alpha["discarded_cost"])) == (1, Decimal("0.0020"))
    assert alpha["unpriced"] == 1
    assert alpha["first_at"] < alpha["last_at"]
    assert [k["kind"] for k in alpha["by_kind"]] == ["aside", "facts", "reply", "summary"]
    assert report["by_story"][0]["story_id"] == str(b.id)


async def test_providers_show_the_cached_share_and_completion_per_call(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    await a_ledger(session)

    report = (await client.get("/spend")).json()

    providers = {p["provider"]: p for p in report["by_provider"]}
    deepinfra = providers["DeepInfra"]
    assert deepinfra["calls"] == 5
    assert deepinfra["cached_share"] == 400 * 5 / 5000
    assert deepinfra["completion_per_call"] == (100 * 4 + 50) // 5
    assert providers["Other"]["cached_share"] == 0
    assert providers["(unknown)"]["calls"] == 1
    assert [p["provider"] for p in report["by_provider"]] == ["DeepInfra", "Other", "(unknown)"]


async def test_the_window_is_from_inclusive_to_exclusive(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    await a_ledger(session)

    march = (
        await client.get(
            "/spend", params={"from_at": "2026-03-01T00:00:00Z", "to_at": "2026-04-01T00:00:00Z"}
        )
    ).json()
    from_the_hour = (await client.get("/spend", params={"from_at": MARCH.isoformat()})).json()
    nothing = (await client.get("/spend", params={"to_at": "2026-01-01T00:00:00Z"})).json()

    assert march["calls"] == 7
    assert Decimal(march["cost"]) == Decimal("0.0049")
    assert from_the_hour["calls"] == 8  # the rows stamped exactly at the start are in
    assert nothing["calls"] == 0
    assert nothing["by_story"] == []
    assert nothing["cached_share"] is None


async def test_a_story_has_its_own_running_total(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    a, _b = await a_ledger(session)

    response = await client.get(f"/stories/{a.id}/spend")

    assert response.status_code == 200
    total = response.json()
    assert total["name"] == "Alpha"
    assert total["calls"] == 6
    assert Decimal(total["cost"]) == Decimal("0.0042")
    assert total["unpriced"] == 1
    assert Decimal(total["discarded_cost"]) == Decimal("0.0020")


async def test_a_deleted_story_keeps_its_name_in_the_report(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    a, _b = await a_ledger(session)
    a.deleted_at = datetime.now(UTC)
    await session.commit()

    report = (await client.get("/spend")).json()

    assert "Alpha" in [s["name"] for s in report["by_story"]]
    assert (await client.get(f"/stories/{a.id}/spend")).status_code == 404
