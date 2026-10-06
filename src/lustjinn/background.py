"""The one retry a background call gets.

Summaries and fact extraction are calls the story makes on its own behalf: nobody is waiting on
them with a message typed, and a refusing summariser is a character that forgets. So they are
asked once more — but only for a failure a second attempt could fix: a timeout, a host that
answered nothing, a 408, a 429, a 5xx. A rejected key or an unknown model is not fixed by asking
again, and a second call would only bill twice for the same refusal.

A reply to the reader is never retried here: the reader sees the failure and decides.
"""

from collections.abc import Awaitable, Callable

from lustjinn.openrouter import ModelError

RETRYABLE_STATUSES = frozenset({200, 408, 429})
"""200 is a host that answered and said nothing — the stream had no content."""


def worth_another_go(error: ModelError) -> bool:
    """Whether a second attempt could end differently."""
    status = error.status
    if status is None:  # a timeout, a dropped connection, a body that was not JSON
        return True
    return status in RETRYABLE_STATUSES or status >= 500


async def once_more_if_worth_it[T](call: Callable[[], Awaitable[T]]) -> T:
    """Runs the call; on a failure a retry could fix, runs it once more. Two failures give up."""
    try:
        return await call()
    except ModelError as error:
        if not worth_another_go(error):
            raise
        return await call()
