"""What the model is sent, for now: the card, the persona, the transcript, an instruction.

Step 5 builds the real context builder — layers in order, a token budget, the audit. This is
its first two layers and its last one, in the order it will keep, so that what the model sees
in step 3 is a prefix of what it will see later.
"""

from collections.abc import Sequence

from lustjinn.models import Character, Message, Persona, Role
from lustjinn.openrouter import ChatMessage

PERSONA_FRAME = (
    "The user is playing the following person. Speak to them as this person, and never write "
    "their words or actions for them.\n\n"
)


def ask_directive(question: str) -> str:
    """The instruction for a question asked out of character. Like every instruction sent, it
    says what it is — not a turn — and what the reply must be: an answer, from what was given."""
    return (
        "Step out of the scene. This is a question from the reader about the story, put to you "
        "as its author, and it is not a turn: nothing here is said aloud by anyone and nothing "
        "that follows happens.\n\n"
        "Answer in your own voice, briefly and plainly. No prose, no dialogue, no action, no "
        "staying in character, and do not move the story forward by so much as a moment.\n\n"
        "Answer only from what you have been given above. Where it does not say, say that it "
        "does not say. Anything you make up here is written down nowhere and will be gone the "
        "moment this is read, so an invented detail becomes something the reader believes and "
        "the story then contradicts.\n\n"
        f"The question: {question.strip()}"
    )


def build(
    character: Character,
    persona: Persona | None,
    history: Sequence[Message],
    *,
    instruction: str | None = None,
) -> list[ChatMessage]:
    """The messages for one call, least volatile first: the character, the persona, the
    transcript as it was spoken, and an instruction for this turn only.

    The instruction goes as `user` when the transcript ends on a reply and as `system` when it
    ends on the reader's own turn — a model given two user turns in a row tends to answer the
    second and forget the first.
    """
    messages = [ChatMessage("system", character.card)]
    if persona is not None:
        messages.append(ChatMessage("system", PERSONA_FRAME + persona.text))
    messages += [ChatMessage(message.role.value, message.text) for message in history]
    if instruction:
        after_a_reply = bool(history) and history[-1].role is Role.ASSISTANT
        messages.append(ChatMessage("user" if after_a_reply else "system", instruction))
    return messages
