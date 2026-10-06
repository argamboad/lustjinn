"""The context builder: layers in order, each framed as the model should read it.

Pure tests — no database, no network — on the dummy character, which is the size of a real one.
"""

from lustjinn.context import (
    MEMORIES_FRAME,
    PERSONA_FRAME,
    WORLD_FRAME,
    Fact,
    Layers,
    Recalled,
    build,
    reader_name,
)
from lustjinn.models import Character, Message, Persona, Role
from scripts.seed_dummy import Dummy


def heron(dummy: Dummy) -> Character:
    return Character(name="The Gilded Heron", card=dummy.card, opening=dummy.opening)


def rowan(dummy: Dummy) -> Persona:
    return Persona(name="Rowan Hale", text=dummy.persona)


def turns(*lines: str) -> list[Message]:
    """A transcript: the reader and the character alternate, the reader first."""
    roles = [Role.USER, Role.ASSISTANT]
    return [Message(sequence=i + 1, role=roles[i % 2], text=line) for i, line in enumerate(lines)]


def test_the_layers_are_sent_least_volatile_first(dummy: Dummy) -> None:
    built = build(
        Layers(
            character=heron(dummy),
            persona=rowan(dummy),
            directives="Pacing: Slow burn.",
            facts=[Fact("Isaure", "owes four hundred and ten marks.")],
            summaries=["Rowan arrived in the fog and took room seven."],
            history=turns("I take the stairs.", "*The stair creaks.*"),
            memories=[Recalled(2, Role.ASSISTANT, "Room seven. Back stairs or front.")],
            trackers="[TRUST] ##........ 20/100",
            instruction="Keep this one short.",
        )
    )

    contents = [m.content for m in built.messages]
    assert contents[0] == dummy.card
    assert contents[1] == PERSONA_FRAME + dummy.persona
    assert contents[2] == "Pacing: Slow burn."
    assert contents[3] == WORLD_FRAME + "Isaure: owes four hundred and ten marks."
    assert contents[4] == "Rowan arrived in the fog and took room seven."
    assert contents[5:7] == ["I take the stairs.", "*The stair creaks.*"]
    assert contents[7] == MEMORIES_FRAME + "[2] The Gilded Heron: Room seven. Back stairs or front."
    assert contents[8] == "[TRUST] ##........ 20/100"
    assert contents[9] == "Keep this one short."
    assert len(contents) == 10


def test_a_layer_with_nothing_in_it_is_left_out(dummy: Dummy) -> None:
    built = build(Layers(character=heron(dummy), history=turns("Hello.")))

    assert [(m.role, m.content) for m in built.messages] == [
        ("system", dummy.card),
        ("user", "Hello."),
    ]


def test_everything_but_the_transcript_and_the_instruction_is_a_system_message(
    dummy: Dummy,
) -> None:
    built = build(
        Layers(
            character=heron(dummy),
            persona=rowan(dummy),
            facts=[Fact("Blake", "sits where he can see the door.")],
            summaries=["Earlier."],
            history=turns("One.", "Two.", "Three."),
            memories=[Recalled(1, Role.USER, "Rowan Hale. A week, perhaps longer.")],
        )
    )

    assert [m.role for m in built.messages] == [
        "system",
        "system",
        "system",
        "system",
        "user",
        "assistant",
        "user",
        "system",
    ]


def test_a_persona_is_framed_as_the_user_rather_than_sent_raw(dummy: Dummy) -> None:
    built = build(Layers(character=heron(dummy), persona=rowan(dummy)))

    assert built.messages[1].content.startswith("The user is playing the following person.")
    assert built.messages[1].content.endswith(dummy.persona)


def test_an_instruction_after_a_reply_arrives_as_the_readers_turn(dummy: Dummy) -> None:
    built = build(
        Layers(
            character=heron(dummy),
            history=turns("Hello.", "Hi."),
            instruction="Step out of the scene.",
        )
    )

    assert (built.messages[-1].role, built.messages[-1].content) == (
        "user",
        "Step out of the scene.",
    )


def test_an_instruction_after_the_readers_own_turn_stays_a_system_note(dummy: Dummy) -> None:
    """Two user turns in a row and a model tends to answer the second and forget the first."""
    built = build(
        Layers(character=heron(dummy), history=turns("Hello."), instruction="Keep it short.")
    )
    empty = build(Layers(character=heron(dummy), instruction="x"))

    assert [m.role for m in built.messages] == ["system", "user", "system"]
    assert built.messages[-1].content == "Keep it short."
    assert empty.messages[-1].role == "system"


def test_recalled_turns_are_named_by_character_and_persona_never_user(dummy: Dummy) -> None:
    built = build(
        Layers(
            character=heron(dummy),
            persona=rowan(dummy),
            memories=[
                Recalled(7, Role.USER, "I set the satchel down."),
                Recalled(8, Role.ASSISTANT, "*Isaure's eyes went to it, and away.*"),
            ],
        )
    )

    assert built.messages[-1].content == (
        MEMORIES_FRAME
        + "[7] Rowan Hale: I set the satchel down.\n"
        + "[8] The Gilded Heron: *Isaure's eyes went to it, and away.*"
    )
    assert "User" not in built.messages[-1].content


def test_without_a_persona_the_reader_is_the_reader(dummy: Dummy) -> None:
    built = build(Layers(character=heron(dummy), memories=[Recalled(1, Role.USER, "I come in.")]))

    assert reader_name(None) == "the reader"
    assert "[1] the reader: I come in." in built.messages[-1].content


def test_the_world_is_one_line_per_fact_under_its_heading(dummy: Dummy) -> None:
    built = build(
        Layers(
            character=heron(dummy),
            facts=[
                Fact("The convoy", "is nine days late."),
                Fact("Mags", "has not slept properly since it was reported overdue."),
            ],
        )
    )

    assert built.messages[1].content == (
        WORLD_FRAME
        + "The convoy: is nine days late.\n"
        + "Mags: has not slept properly since it was reported overdue."
    )


def test_summaries_follow_one_another_with_no_heading(dummy: Dummy) -> None:
    built = build(Layers(character=heron(dummy), summaries=["First stretch.", "Second."]))

    assert built.messages[1].content == "First stretch.\n\nSecond."
