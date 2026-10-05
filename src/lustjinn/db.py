"""The database: one engine for the process, one session per request."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lustjinn.settings import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """The engine owns the connection pool. Created on first use, once per process."""
    # pool_pre_ping tests a pooled connection before handing it out, so one the server dropped
    # while idle (a sleeping cloud database does that) is replaced instead of failing a request.
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after a commit without another query —
    # the default would reload them lazily, which async code cannot do implicitly.
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """One session per request. FastAPI injects it; it closes when the request ends."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Close the pool at shutdown, if the engine was ever created."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
