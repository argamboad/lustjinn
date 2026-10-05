"""Reading the API's streamed responses in tests: the events, and the three questions asked of
them — what was streamed, how it ended, and what the model was sent."""

import json
from dataclasses import dataclass
from typing import Any

import httpx2

from lustjinn.sse import events

Json = dict[str, Any]


@dataclass(frozen=True)
class Streamed:
    status: int
    events: list[tuple[str | None, Json]]
    """Each event's name and its JSON payload, in order."""

    @property
    def text(self) -> str:
        """The reply as it was streamed: every `delta` joined."""
        return "".join(data["text"] for name, data in self.events if name == "delta")

    @property
    def last(self) -> tuple[str | None, Json]:
        return self.events[-1]

    @property
    def done(self) -> Json:
        name, data = self.last
        assert name == "done", f"the stream ended with {name}: {data}"
        return data

    @property
    def error(self) -> Json:
        name, data = self.last
        assert name == "error", f"the stream ended with {name}: {data}"
        return data


async def stream(client: httpx2.AsyncClient, url: str, **body: object) -> Streamed:
    """POSTs and reads the whole stream. A refusal before the stream (a 4xx) is returned as a
    single unnamed event carrying the JSON body."""
    found: list[tuple[str | None, Json]] = []
    async with client.stream("POST", url, json=body) as response:
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            found = [(e.name, json.loads(e.data)) async for e in events(response.aiter_lines())]
        else:
            found = [(None, json.loads(await response.aread()))]
    return Streamed(response.status_code, found)


async def send(client: httpx2.AsyncClient, story_id: object, text: str) -> Streamed:
    return await stream(client, f"/stories/{story_id}/send", text=text)
