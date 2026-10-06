"""The wording sent to the model for the turns a reader asks for without writing one.

A direction cannot go to the model bare. Every layer above it has spent its words telling the
model to stay in character and to leave the reader's turn alone, and a bare `have Mags leave`
arriving after all of that reads as something the reader said aloud. Each frame here says whose
instruction this is and restates the one rule it is most likely to be read as suspending.
"""

CARRY_ON = (
    "Carry the scene forward yourself. Let time pass and let the world act: other characters "
    "speak, move, arrive, react to one another. This reply does not hand the scene back and "
    "does not wait — the user's silence is not a cue to stop. Still never write their words, "
    "actions or thoughts; leave them something to step into instead."
)
"""The next beat with nothing from the reader. A card's fail-safe rule — hand the scene back
rather than assume what the user does — is phrased as "no exception", and it outranks a polite
"without waiting": the reply comes back as a beat that stops and asks. So this separates the two
halves the rule conflates. Never writing the user still holds; stopping for them does not, this
turn."""

DIRECTION_FRAME = (
    "A direction for this reply, from the reader, out of character. It is not something anyone "
    "said aloud and nobody in the scene knows it was given. Write the next turn following it, "
    "and still never write the user's words, actions or thoughts.\n\n"
)


def direction(text: str) -> str:
    """A free-form direction for the next turn, framed. It replaces the carry-on wording rather
    than joining it: both say what this turn should be, and two answers to that question in one
    prompt is how a reply comes back trying to satisfy neither."""
    return DIRECTION_FRAME + text.strip()


def split(argument: str) -> tuple[str, str]:
    """`/do`'s argument: the direction, and the message under it if there is one. The first
    blank line divides them, so a direction may run to several lines and a message may too."""
    head, _, tail = argument.strip().partition("\n\n")
    return head.strip(), tail.strip()
