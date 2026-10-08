"""Guessing is throttled (#84): failures are counted in the database, a lockout refuses even the
right password, it lifts as the failures age out, and a success clears the count."""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.main import create_app
from lustjinn.models import SignInFailure
from lustjinn.settings import Settings

RIGHT = {"username": "reader", "password": "correct horse battery staple"}
WRONG = {"username": "reader", "password": "tr0ub4dor&3"}


async def sign_in(client: httpx2.AsyncClient, body: dict[str, str]) -> httpx2.Response:
    return await client.post("/auth/sign-in", json=body)


async def failures(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(SignInFailure)) or 0


async def test_every_wrong_sign_in_is_recorded(
    anonymous: httpx2.AsyncClient, session: AsyncSession
) -> None:
    for _ in range(3):
        assert (await sign_in(anonymous, WRONG)).status_code == 401
    assert await failures(session) == 3


async def test_the_limit_locks_sign_in_even_for_the_right_password(
    anonymous: httpx2.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    for _ in range(settings.sign_in_attempts):
        assert (await sign_in(anonymous, WRONG)).status_code == 401

    refused = await sign_in(anonymous, RIGHT)

    assert refused.status_code == 429
    assert refused.json()["detail"] == "Too many failed sign-ins. Try again in 15 minutes."
    retry = int(refused.headers["Retry-After"])
    assert 14 * 60 < retry <= 15 * 60
    # A refusal while locked is not another failure: the lockout does not extend itself.
    assert await failures(session) == settings.sign_in_attempts


async def test_the_lockout_lifts_as_the_failures_age_out(
    anonymous: httpx2.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    now = datetime.now(UTC)
    # Five failures: four from long ago in the window, the oldest just about to leave it.
    window = timedelta(minutes=settings.sign_in_window_minutes)
    session.add(SignInFailure(at=now - window + timedelta(seconds=30)))
    for minutes in (1, 2, 3, 4):
        session.add(SignInFailure(at=now - timedelta(minutes=minutes)))
    await session.commit()

    locked = await sign_in(anonymous, RIGHT)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) <= 30
    assert locked.json()["detail"] == "Too many failed sign-ins. Try again in a minute."

    # The oldest leaves the window: four remain, under the limit, and the right password works.
    oldest = await session.scalar(select(SignInFailure).order_by(SignInFailure.at).limit(1))
    assert oldest is not None
    oldest.at = now - window - timedelta(seconds=1)
    await session.commit()
    assert (await sign_in(anonymous, RIGHT)).status_code == 200


async def test_a_right_password_under_the_limit_clears_the_count(
    anonymous: httpx2.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    for _ in range(settings.sign_in_attempts - 1):
        await sign_in(anonymous, WRONG)

    assert (await sign_in(anonymous, RIGHT)).status_code == 200
    assert await failures(session) == 0
    assert (await sign_in(anonymous, WRONG)).status_code == 401  # a fresh allowance


async def test_failures_older_than_the_window_are_pruned(
    anonymous: httpx2.AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    long_ago = datetime.now(UTC) - timedelta(minutes=settings.sign_in_window_minutes, hours=1)
    for _ in range(10):
        session.add(SignInFailure(at=long_ago))
    await session.commit()

    assert (await sign_in(anonymous, WRONG)).status_code == 401
    assert await failures(session) == 1


async def test_a_wrong_password_waits_before_it_is_answered(
    anonymous: httpx2.AsyncClient, tune: Callable[..., Settings]
) -> None:
    tune(sign_in_failure_delay_seconds=0.3)

    started = time.perf_counter()
    wrong = await sign_in(anonymous, WRONG)
    waited = time.perf_counter() - started
    started = time.perf_counter()
    right = await sign_in(anonymous, RIGHT)
    answered = time.perf_counter() - started

    assert wrong.status_code == 401
    assert waited >= 0.3
    assert right.status_code == 200
    assert answered < 0.3


async def test_the_limit_and_the_window_are_settings(
    anonymous: httpx2.AsyncClient, tune: Callable[..., Settings]
) -> None:
    tune(sign_in_attempts=2, sign_in_window_minutes=60)

    await sign_in(anonymous, WRONG)
    await sign_in(anonymous, WRONG)
    refused = await sign_in(anonymous, RIGHT)

    assert refused.status_code == 429
    assert refused.json()["detail"] == "Too many failed sign-ins. Try again in 60 minutes."


async def test_the_docs_are_off_unless_the_settings_turn_them_on(settings: Settings) -> None:
    for docs, expected in ((False, 404), (True, 200)):
        app = create_app(settings.model_copy(update={"docs": docs}))
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                assert (await client.get(path)).status_code == expected, (docs, path)


def test_the_docs_default_to_off() -> None:
    assert Settings.model_fields["docs"].default is False
