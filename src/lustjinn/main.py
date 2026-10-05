"""The FastAPI application: the object uvicorn serves."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from lustjinn.db import dispose_engine
from lustjinn.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Runs once around the app's life: before `yield` at start-up, after it at shutdown."""
    get_settings()  # a missing or invalid setting stops the app here, not on the first request
    yield
    await dispose_engine()


app = FastAPI(title="Lustjinn", lifespan=lifespan)


class Health(BaseModel):
    status: Literal["ok"]
    commit: str | None
    """The deployed commit (Render's `RENDER_GIT_COMMIT`); None when not running on Render."""


@app.get("/health")
async def health() -> Health:
    """Answers while the process is up. Render, the deploy job and the PWA poll it."""
    return Health(status="ok", commit=os.environ.get("RENDER_GIT_COMMIT"))
