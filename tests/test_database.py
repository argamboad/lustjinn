from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.db import dispose_engine, get_engine, get_session
from lustjinn.settings import get_settings


async def test_the_database_answers(session: AsyncSession) -> None:
    assert await session.scalar(text("SELECT 1")) == 1


async def test_it_is_postgres_17(session: AsyncSession) -> None:
    version = await session.scalar(text("SHOW server_version"))

    assert str(version).startswith("17.")


async def test_pgvector_can_be_enabled(session: AsyncSession) -> None:
    """The image ships the extension; the memory step will CREATE EXTENSION it."""
    available = await session.scalar(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    )

    assert available == 1


async def test_a_test_leaves_nothing_behind_part_one(session: AsyncSession) -> None:
    await session.execute(text("CREATE TABLE left_behind (id int)"))
    await session.commit()  # even a commit stays inside the test's transaction


async def test_a_test_leaves_nothing_behind_part_two(session: AsyncSession) -> None:
    assert await session.scalar(text("SELECT to_regclass('left_behind')")) is None


async def test_the_apps_own_session_reaches_the_database(
    database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The path a request takes: settings → engine → session."""
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("LUSTJINN_DATABASE_URL", database_url)
    monkeypatch.setenv("LUSTJINN_USERNAME", "reader")
    monkeypatch.setenv("LUSTJINN_PASSWORD", "a password")
    monkeypatch.setenv("LUSTJINN_TOKEN_SECRET", "x" * 32)
    get_settings.cache_clear()
    try:
        async for session in get_session():
            assert (
                await session.scalar(text("SELECT current_database()"))
                == (database_url.rsplit("/", 1)[1])
            )
        assert get_engine.cache_info().currsize == 1
    finally:
        await dispose_engine()
        get_settings.cache_clear()

    assert get_engine.cache_info().currsize == 0
