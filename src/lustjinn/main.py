"""The FastAPI application: the object uvicorn serves."""

import os
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Lustjinn")


class Health(BaseModel):
    status: Literal["ok"]
    commit: str | None
    """The deployed commit (Render's `RENDER_GIT_COMMIT`); None when not running on Render."""


@app.get("/health")
async def health() -> Health:
    """Answers while the process is up. Render, the deploy job and the PWA poll it."""
    return Health(status="ok", commit=os.environ.get("RENDER_GIT_COMMIT"))
