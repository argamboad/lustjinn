"""What a streamed route sends back: server-sent events, the events every command can end on,
and the response that carries them.

Shared by every module that answers `/send` — turns, asides, recap, facts, trackers — so none
of them has to import another to say "done" (#133). `sse.py` is the wire format; this is what
the API says over it.
"""

from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lustjinn.sse import format_event
from lustjinn.stories import MessageOut

# How the stream is described on /docs: FastAPI cannot read it off a StreamingResponse.
STREAMED: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "content": {"text/event-stream": {}},
        "description": "Server-sent events: `delta` while the reply is written, then `done` or "
        "`error`.",
    }
}


class Failed(BaseModel):
    """The last event when the model did not answer."""

    kind: Literal["error"] = "error"
    detail: str
    sent: MessageOut | None
    """The reader's message, which was kept. Do not send it again."""


class Said(BaseModel):
    """The last — and only — event of a command that answers in words and stores no turn:
    shown once, kept nowhere."""

    kind: Literal["said"] = "said"
    text: str


def event(name: str, payload: BaseModel) -> str:
    return format_event(name, payload.model_dump(mode="json"))


def delta(text: str) -> str:
    """A piece of the reply, as the model wrote it."""
    return format_event("delta", {"text": text})


async def started(events: AsyncIterator[str]) -> AsyncIterator[str]:
    """Runs a stream up to its first event, so what it refuses is refused with a status code
    before the response has begun, and what it says is still said as a stream."""
    first = await anext(events)

    async def rest() -> AsyncIterator[str]:
        yield first
        async for more in events:
            yield more

    return rest()


def streamed(events: AsyncIterator[str]) -> StreamingResponse:
    # X-Accel-Buffering: a proxy in front (Render's, nginx) must pass each event on as it comes.
    return StreamingResponse(
        events, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )
