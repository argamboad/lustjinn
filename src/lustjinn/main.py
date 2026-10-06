"""The FastAPI application: the object uvicorn serves."""

import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from lustjinn import (
    auth,
    dials,
    editing,
    export,
    facts,
    library,
    search,
    spend,
    stories,
    story_model,
    trackers,
    turns,
)
from lustjinn.db import dispose_engine
from lustjinn.openrouter import close_http
from lustjinn.settings import Settings, get_settings

# Sent with every response. The API serves private stories: nothing should cache them, pass
# their address on, index them, or guess at their content type.
PRIVATE = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
}


class Health(BaseModel):
    status: Literal["ok"]
    commit: str | None
    """The deployed commit (Render's `RENDER_GIT_COMMIT`); None when not running on Render."""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Runs once around the app's life: before `yield` at start-up, after it at shutdown."""
    get_settings()  # a missing or invalid setting stops the app here, not on the first request
    yield
    await dispose_engine()
    await close_http()


def _cors_origins(settings: Settings | None) -> list[str]:
    if settings is not None:
        return settings.cors_origins
    try:
        return get_settings().cors_origins
    except ValidationError:
        # Importing this module must not fail on incomplete settings (the tests import it with
        # none). The lifespan above reports the real problem when the app actually starts.
        return []


def create_app(settings: Settings | None = None) -> FastAPI:
    """Builds the application. `settings` is for tests; normally they come from the environment."""
    app = FastAPI(title="Lustjinn", lifespan=lifespan)

    # CORS: which browser origins may call this API. The token travels in a header, not a
    # cookie, so no credentials are allowed through.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def keep_it_private(  # pyright: ignore[reportUnusedFunction] — registered by the decorator
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(PRIVATE)
        return response

    @app.exception_handler(RequestValidationError)
    async def say_what_is_wrong_without_repeating_it(  # pyright: ignore[reportUnusedFunction]
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        """A 422 that names the field and the problem, but never echoes what was sent.

        FastAPI's default includes the rejected input — which, for a malformed sign-in, is the
        password, and for a story is its text. Neither belongs in a response body or a log.
        """
        problems = [
            {"type": problem["type"], "loc": problem["loc"], "msg": problem["msg"]}
            for problem in error.errors()
        ]
        return JSONResponse({"detail": problems}, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.get("/health")
    async def health() -> Health:  # pyright: ignore[reportUnusedFunction]
        """Answers while the process is up. Open to anyone: it says nothing about the stories."""
        return Health(status="ok", commit=os.environ.get("RENDER_GIT_COMMIT"))

    app.include_router(auth.router)
    # Everything below needs a valid token. A new router goes here, behind the guard, by default.
    app.include_router(stories.router, dependencies=[Depends(auth.require_user)])
    app.include_router(turns.router, dependencies=[Depends(auth.require_user)])
    app.include_router(library.router, dependencies=[Depends(auth.require_user)])
    app.include_router(dials.router, dependencies=[Depends(auth.require_user)])
    app.include_router(trackers.router, dependencies=[Depends(auth.require_user)])
    app.include_router(story_model.router, dependencies=[Depends(auth.require_user)])
    app.include_router(editing.router, dependencies=[Depends(auth.require_user)])
    app.include_router(search.router, dependencies=[Depends(auth.require_user)])
    app.include_router(export.router, dependencies=[Depends(auth.require_user)])
    app.include_router(spend.router, dependencies=[Depends(auth.require_user)])
    app.include_router(facts.router, dependencies=[Depends(auth.require_user)])
    return app


app = create_app()
