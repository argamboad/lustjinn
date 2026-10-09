"""What a route asks FastAPI for, declared once: the database session, the settings, the model.

A parameter annotated `session: Session` gets the request's session; FastAPI calls `get_session`
and passes the result in, and a test swaps it through `app.dependency_overrides`. Every route
module imports these rather than declaring its own, so injection changes in one place (#129).
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn.db import get_session
from lustjinn.openrouter import OpenRouter, get_openrouter
from lustjinn.settings import Settings, get_settings

Session = Annotated[AsyncSession, Depends(get_session)]
"""The request's database session, closed when the route function returns."""

StreamingSession = Annotated[AsyncSession, Depends(get_session, scope="request")]
"""The same session, kept open until the response has been sent. A streamed reply runs after the
route function has returned; with `Session` its session would already be closed."""

CurrentSettings = Annotated[Settings, Depends(get_settings)]
Model = Annotated[OpenRouter, Depends(get_openrouter)]
