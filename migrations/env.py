"""Alembic runs this file for every command: it says which database, and which models."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from lustjinn.models import Base
from lustjinn.settings import get_settings

# What the models say the schema should be; `alembic revision --autogenerate` and the
# migrations-match-the-models test compare the database against it.
target_metadata = Base.metadata


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    # One transaction per run: Postgres can roll back schema changes, so a migration that
    # fails halfway leaves nothing behind.
    with context.begin_transaction():
        context.run_migrations()


async def run_with_the_settings_database() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        # Alembic itself is synchronous; run_sync lends it this async connection.
        await connection.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline mode (--sql) is not set up for this project.")

# The tests hand over a connection to their throwaway database; the command line gets the one
# from the settings.
given: Connection | None = context.config.attributes.get("connection")
if given is not None:
    run(given)
else:
    asyncio.run(run_with_the_settings_database())
