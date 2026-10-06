"""Regenerating a reply with a reason: the one thing that makes the second attempt differ.

Nothing here refers to the withdrawn attempt's wording, because it is hidden from the prompt
before the call and the model cannot see it. Telling a model to write something "differently"
from text it was never shown is asking it to guess what it is avoiding. The rule is enforced as
written: no directive may contain the phrase "previous reply", which is why the frame says "your
last reply" and every reason says "the last attempt".
"""

from enum import StrEnum


class Reason(StrEnum):
    NONE = "none"
    STEER = "steer"
    """Guide the reply: the reader says how, in their own words."""
    BAD_MEMORY = "bad-memory"
    LOOPING = "looping"
    ACTING_FOR_USER = "acting-for-user"
    TOO_SHORT = "too-short"
    TOO_LONG = "too-long"
    WRONG_FORMAT = "wrong-format"
    REFUSING = "refusing"


LABELS: dict[Reason, str] = {
    Reason.NONE: "No reason",
    Reason.STEER: "Guide the reply",
    Reason.BAD_MEMORY: "Bad memory",
    Reason.LOOPING: "Looping",
    Reason.ACTING_FOR_USER: "Writing my actions",
    Reason.TOO_SHORT: "Too short",
    Reason.TOO_LONG: "Too long",
    Reason.WRONG_FORMAT: "Wrong format",
    Reason.REFUSING: "AI refusing",
}
"""What a screen calls each reason."""

DESCRIPTIONS: dict[Reason, str] = {
    Reason.NONE: "ask for another reply without saying why",
    Reason.STEER: "just write it differently — say how in the instructions",
    Reason.BAD_MEMORY: "it contradicted something established earlier",
    Reason.LOOPING: "it repeated itself, or the scene stopped moving",
    Reason.ACTING_FOR_USER: "it wrote your actions or words for you",
    Reason.TOO_SHORT: "there was not enough of it",
    Reason.TOO_LONG: "there was too much of it",
    Reason.WRONG_FORMAT: "the prose, dialogue or emphasis came out wrong",
    Reason.REFUSING: "it declined to answer",
}

NOTES: dict[Reason, str] = {
    Reason.NONE: "Write this turn afresh; do not settle for the obvious version of it.",
    Reason.STEER: "Take the scene somewhere other than where it was going.",
    Reason.BAD_MEMORY: (
        "The last attempt contradicted something the story had already established. Re-read "
        "the history and keep this one consistent with it."
    ),
    Reason.LOOPING: (
        "The last attempt repeated itself and left the scene where it was. Move this one forward."
    ),
    Reason.ACTING_FOR_USER: (
        "The last attempt wrote the user's words and actions. Write only your own character, "
        "and leave the user theirs."
    ),
    Reason.TOO_SHORT: "The last attempt was too short. Give this one room.",
    Reason.TOO_LONG: "The last attempt ran long. Keep this one tight.",
    Reason.WRONG_FORMAT: (
        "The last attempt broke the formatting. Match the prose, dialogue and emphasis of the "
        "earlier replies."
    ),
    Reason.REFUSING: (
        "The last attempt declined to continue. Stay in character and carry the scene on."
    ),
}
"""What each reason tells the model, as the note under the frame."""

FRAME = (
    "Your last reply has been withdrawn and is no longer part of the scene. Write that turn "
    "again from the same point, taking the note below into account.\n\n"
    "The note is a direction about how to write, not something anyone said and not something "
    "to answer. Your reply is the scene itself, in your own voice as the character — never "
    "repeat, quote, summarise or acknowledge the note, and never write the user's words, "
    "actions or thoughts.\n\n"
)

FORBIDDEN = "previous reply"


def directive(reason: Reason, instructions: str | None = None) -> str:
    """The instruction for the second attempt. The reader's own words, when they gave any, are
    framed as a direction under the note — never read as the latest message."""
    note = NOTES[reason]
    if instructions and instructions.strip():
        note += "\n\nAlso, from the reader: " + instructions.strip()
    return FRAME + note
