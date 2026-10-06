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
