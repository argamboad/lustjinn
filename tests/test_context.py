"""The context builder: layers in order, each framed as the model should read it.

Pure tests — no database, no network — on the dummy character, which is the size of a real one.
"""

from lustjinn import tokens
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


# --- the budget -------------------------------------------------------------------------------

FILLER = "The tide bell rang twice and nobody in the common room looked up from their cards. "


def long_story(n: int) -> list[Message]:
    """n turns of about 20 tokens each, numbered so a test can see which ones survived."""
    return turns(*(f"Turn {i + 1}. {FILLER}" for i in range(n)))


def memories(n: int) -> list[Recalled]:
    return [Recalled(i + 1, Role.ASSISTANT, f"Memory {i + 1}. {FILLER * 2}") for i in range(n)]


def test_without_a_budget_everything_is_sent(dummy: Dummy) -> None:
    built = build(Layers(character=heron(dummy), history=long_story(300)))

    assert len(built.messages) == 301
    assert built.budget is None
    assert built.spent["history"].dropped == 0


def test_the_transcript_is_what_gives_when_the_budget_binds(dummy: Dummy) -> None:
    fixed = tokens.for_message(dummy.card) + tokens.for_message(PERSONA_FRAME + dummy.persona)
    budget = fixed + 1000

    built = build(
        Layers(character=heron(dummy), persona=rowan(dummy), history=long_story(200)),
        budget=budget,
    )

    assert built.messages[0].content == dummy.card  # the fixed layers are all there
    assert built.messages[1].content.endswith(dummy.persona)
    assert 0 < built.spent["history"].dropped < 200
    assert built.estimated_tokens <= budget


def test_the_turns_kept_are_the_ones_nearest_the_reply(dummy: Dummy) -> None:
    built = build(
        Layers(character=heron(dummy), history=long_story(100)),
        budget=tokens.for_message(dummy.card) + 500,
    )

    kept = [m.content for m in built.messages[1:]]
    assert kept[-1].startswith("Turn 100.")
    numbers = [int(line.split(".")[0].split()[1]) for line in kept]
    assert numbers == list(range(numbers[0], 101))  # contiguous, ending on the newest


def test_a_budget_too_small_for_even_the_fixed_layers_still_sends_the_newest_turn(
    dummy: Dummy,
) -> None:
    """Over budget rather than a reply to nothing."""
    built = build(Layers(character=heron(dummy), history=long_story(10)), budget=1000)

    assert [m.content for m in built.messages] == [dummy.card, "Turn 10. " + FILLER]
    assert built.spent["history"].dropped == 9
    assert built.estimated_tokens > 1000


def test_the_instruction_is_counted_before_the_history_is_fitted(dummy: Dummy) -> None:
    """An instruction is never squeezed out by old turns: it is fixed, and the history fits
    around it."""
    budget = tokens.for_message(dummy.card) + 300
    note = "Keep this one short. " * 10
    with_note = build(
        Layers(character=heron(dummy), history=long_story(50), instruction=note), budget=budget
    )
    without = build(Layers(character=heron(dummy), history=long_story(50)), budget=budget)

    assert with_note.messages[-1].content == note
    assert with_note.spent["history"].dropped > without.spent["history"].dropped


def test_recalled_turns_cannot_take_more_than_their_share_of_the_budget(dummy: Dummy) -> None:
    built = build(Layers(character=heron(dummy), memories=memories(40)), budget=10_000)

    assert built.spent["memories"].tokens <= 10_000 * 10 // 100
    assert 0 < built.spent["memories"].dropped < 40


def test_the_recall_share_is_a_setting(dummy: Dummy) -> None:
    layers = Layers(character=heron(dummy), memories=memories(40))

    tight = build(layers, budget=10_000, recall_percent=5)
    loose = build(layers, budget=10_000, recall_percent=50)

    assert tight.spent["memories"].dropped > loose.spent["memories"].dropped
    assert loose.spent["memories"].tokens <= 5000


def test_recalled_turns_are_kept_by_relevance_and_read_in_story_order(dummy: Dummy) -> None:
    """The list arrives most relevant first; the cap keeps from the top; the model then reads
    the survivors as a transcript, oldest first."""
    long = FILLER * 6
    recalled = [
        Recalled(30, Role.ASSISTANT, "Thirty, most relevant. " + long),
        Recalled(10, Role.USER, "Ten, next. " + long),
        Recalled(20, Role.ASSISTANT, "Twenty, barely relevant. " + long),
    ]
    two_fit = tokens.for_message(MEMORIES_FRAME) + 2 * tokens.for_message(long) + 60

    built = build(
        Layers(character=heron(dummy), persona=rowan(dummy), memories=recalled),
        budget=two_fit * 10,  # the cap is 10%: room for two of the three
        recall_percent=10,
    )

    lines = built.messages[-1].content.splitlines()[1:]
    assert [line.split("]")[0] for line in lines] == ["[10", "[30"]
    assert built.spent["memories"].dropped == 1


def test_a_recalled_turn_that_does_not_fit_is_skipped_rather_than_ending_the_search(
    dummy: Dummy,
) -> None:
    recalled = [
        Recalled(1, Role.ASSISTANT, "Short one. "),
        Recalled(2, Role.ASSISTANT, "A very long memory. " + FILLER * 40),
        Recalled(3, Role.ASSISTANT, "Another short one. "),
    ]

    built = build(Layers(character=heron(dummy), memories=recalled), budget=1500, recall_percent=10)

    assert "Short one." in built.messages[-1].content
    assert "Another short one." in built.messages[-1].content
    assert "very long" not in built.messages[-1].content


def test_the_accounting_names_every_layer_that_contributed(dummy: Dummy) -> None:
    built = build(
        Layers(
            character=heron(dummy),
            persona=rowan(dummy),
            summaries=["Earlier."],
            history=turns("One.", "Two."),
            instruction="Go on.",
        ),
        budget=32_000,
    )

    assert list(built.spent) == ["character", "persona", "summaries", "history", "instruction"]
    assert built.spent["character"].tokens == tokens.for_message(dummy.card)
    assert built.spent["history"].tokens == tokens.for_message("One.") + tokens.for_message("Two.")
    assert built.estimated_tokens == sum(s.tokens for s in built.spent.values())
    assert built.budget == 32_000
