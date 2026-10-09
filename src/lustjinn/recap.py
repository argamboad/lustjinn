"""`/recap`: the story so far, for a reader coming back after a break. No model call, nothing
stored: the latest summary under "Earlier:", then the last few turns word for word."""

from collections.abc import AsyncIterator, Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from lustjinn import memory
from lustjinn.models import Message, Role, Story
from lustjinn.stories import visible_messages
from lustjinn.streams import Said, event

RECAP_TURNS = 4
"""How many turns a recap shows when none is asked for."""
MOST_RECAP_TURNS = 20
"""The most it shows, whatever is asked for."""

HEADING = "(Recap, out of character — nothing stored, nothing billed.)"


def count_from(argument: str) -> int:
    """`/recap`'s argument as a count, clamped to the range. A word is a `ValueError`."""
    typed = argument.strip()
    if not typed:
        return RECAP_TURNS
    if not typed.isdigit():
        raise ValueError(f"/recap takes a number of turns, up to {MOST_RECAP_TURNS}")
    return min(max(int(typed), 1), MOST_RECAP_TURNS)


def format_recap(
    speaker: str, latest_summary: str | None, turns: Sequence[Message], count: int
) -> str:
    """The recap as plain text. `speaker` is what to call the replies' author; the reader is
    "You", since this is shown to them and never to a model."""
    text = HEADING
    if latest_summary and latest_summary.strip():
        text += "\n\nEarlier:\n" + latest_summary.strip()
    if not turns:
        return text + "\n\nNothing has been said yet."
    shown = list(turns)[-min(max(count, 1), MOST_RECAP_TURNS) :]
    text += "\n\nThe last turn:" if len(shown) == 1 else f"\n\nThe last {len(shown)} turns:"
    for turn in shown:
        who = "You" if turn.role is Role.USER else speaker
        text += f"\n\n{who}:\n{turn.text.strip()}"
    return text


async def recap_of(session: AsyncSession, story: Story, argument: str) -> AsyncIterator[str]:
    """`/recap [turns]`: the latest summary and the last turns. Nothing stored, nothing billed.
    A count that is not a number is refused before the stream's first event."""
    try:
        count = count_from(argument)
    except ValueError as why:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{why} — nothing was stored."
        ) from None
    summaries = await memory.summaries_of(session, story.id)
    latest = summaries[-1].text if summaries else None
    turns = await visible_messages(session, story.id)
    yield event("done", Said(text=format_recap(story.character.name, latest, turns, count)))
