"""`/recap`: the story so far, for a reader coming back after a break. No model call, nothing
stored: the latest summary under "Earlier:", then the last few turns word for word."""

from collections.abc import Sequence

from lustjinn.models import Message, Role

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
