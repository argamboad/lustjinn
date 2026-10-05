"""The server-sent events format, read and written."""

import json
from collections.abc import AsyncIterator

from lustjinn.sse import Event, events, format_event


async def lines(text: str) -> AsyncIterator[str]:
    for line in text.splitlines(keepends=True):
        yield line


async def collect(text: str) -> list[Event]:
    return [event async for event in events(lines(text))]


async def test_a_blank_line_ends_an_event() -> None:
    found = await collect("data: one\n\ndata: two\n\n")

    assert found == [Event("one"), Event("two")]


async def test_an_event_may_carry_a_name() -> None:
    found = await collect("event: delta\ndata: {}\n\n")

    assert found == [Event("{}", "delta")]


async def test_comments_are_skipped() -> None:
    """OpenRouter sends `: OPENROUTER PROCESSING` while the prompt is being read."""
    found = await collect(": OPENROUTER PROCESSING\n\n: still going\ndata: x\n\n")

    assert found == [Event("x")]


async def test_several_data_lines_join_with_newlines() -> None:
    found = await collect("data: first\ndata: second\n\n")

    assert found == [Event("first\nsecond")]


async def test_one_space_after_the_colon_is_separator_and_the_rest_is_data() -> None:
    found = await collect("data:  two spaces\n\ndata:none\n\n")

    assert found == [Event(" two spaces"), Event("none")]


async def test_a_stream_that_ends_without_a_blank_line_still_yields_the_last_event() -> None:
    found = await collect("data: [DONE]")

    assert found == [Event("[DONE]")]


async def test_windows_line_endings_are_tolerated() -> None:
    found = await collect("event: a\r\ndata: 1\r\n\r\n")

    assert found == [Event("1", "a")]


async def test_what_is_written_can_be_read_back() -> None:
    text = format_event("delta", {"text": "She looks up — « ¿qué? »"})

    [event] = await collect(text)
    assert event.name == "delta"
    assert json.loads(event.data) == {"text": "She looks up — « ¿qué? »"}
    assert text.endswith("\n\n")
