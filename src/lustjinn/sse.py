"""Server-sent events, both ways: read from the model's stream, written to our own clients.

SSE is a plain text format over one long HTTP response. Each event is a few `name: value` lines
and ends with a blank line:

    event: delta
    data: {"text": "She looks up"}

    : a line starting with a colon is a comment — keep-alives look like this

    data: [DONE]

Only `event` and `data` matter here. A `data` line may repeat; the values join with newlines.
"""

import json
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    data: str
    name: str | None = None
    """The `event:` line, when the stream names its events. OpenRouter does not; we do."""


async def events(lines: AsyncIterable[str]) -> AsyncIterator[Event]:
    """Turns a stream of lines into events. A blank line dispatches what was gathered."""
    name: str | None = None
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield Event("\n".join(data), name)
            name, data = None, []
        elif line.startswith(":"):
            continue  # a comment
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")  # one leading space is part of the separator
            if field == "data":
                data.append(value)
            elif field == "event":
                name = value
            # `id` and `retry` are part of the format but nothing here uses them.
    if data:  # a stream that ended without a final blank line
        yield Event("\n".join(data), name)


def format_event(name: str, data: object) -> str:
    """One event, ready to write: the name, the data as JSON, the blank line that ends it."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
