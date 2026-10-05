"""Fixtures every test can ask for by name. pytest finds this file by itself.

The database tests run against a real Postgres — the one from docker-compose.yml locally, a
service container in CI — but never against the data being played with: the session starts by
creating a throwaway database and ends by dropping it, and every test runs inside a transaction
that is rolled back.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx2
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from lustjinn.db import get_session
from lustjinn.main import app

# Any database on the server will do to connect to; the tests create their own beside it.
SERVER = os.environ.get(
    "LUSTJINN_TEST_DATABASE_URL", "postgresql+asyncpg://lustjinn:lustjinn@localhost:5440/postgres"
)


def migrate(connection: Connection, revision: str = "head") -> None:
    """Runs Alembic on this connection: up to `revision`, or down to it when it is "base"."""
    config = Config(Path(__file__).parent.parent / "alembic.ini")
    config.attributes["connection"] = connection  # migrations/env.py looks for it
    if revision == "base":
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


@pytest_asyncio.fixture(scope="session")
async def database_url() -> AsyncGenerator[str]:
    """Creates an empty database for this test run and drops it afterwards."""
    name = f"lustjinn_test_{uuid.uuid4().hex[:12]}"
    # CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    server = create_async_engine(SERVER, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with server.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OSError as error:
        pytest.exit(
            f"The tests need Postgres and could not reach it ({error}). "
            "Start it with `docker compose up -d`.",
            returncode=1,
        )
    yield make_url(SERVER).set(database=name).render_as_string(hide_password=False)
    async with server.connect() as connection:
        await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    await server.dispose()


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    """The throwaway database with every migration applied — the real ones, not `create_all`."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(migrate)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """A session whose work disappears when the test ends.

    The test's connection opens a transaction that is never committed. The session joins it with
    savepoints, so code under test can call `commit()` as it would in production and still be
    rolled back here.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[httpx2.AsyncClient]:
    """An HTTP client that calls the app in-process, with the app using the test's session."""

    async def use_the_tests_session() -> AsyncGenerator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = use_the_tests_session
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
