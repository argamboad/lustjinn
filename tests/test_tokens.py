"""Counting tokens with the model's own vocabulary."""

from lustjinn.tokens import PER_MESSAGE, count, encoding, for_message
from scripts.seed_dummy import Dummy


def test_the_vocabulary_is_the_one_the_model_counts_with() -> None:
    assert encoding().name == "o200k_base"


def test_a_short_sentence_counts_as_the_model_would() -> None:
    """Two words, two tokens — the leading space belongs to the second."""
    assert count("hello world") == 2
    assert count("") == 0


def test_framing_is_counted_even_for_a_turn_with_no_text() -> None:
    assert for_message("") == PER_MESSAGE
    assert for_message("hello world") == 2 + PER_MESSAGE


def test_a_marker_the_vocabulary_treats_as_special_is_just_text_here() -> None:
    """tiktoken refuses `<|endoftext|>` by default; a card that quotes one must still count."""
    assert count("<|endoftext|>") > 0


def test_the_dummy_card_is_the_size_of_a_real_one(dummy: Dummy) -> None:
    """The budget decisions below are made against cards of this order, not four-token ones."""
    assert 2000 <= count(dummy.card) <= 6000


def test_counting_is_a_pure_function() -> None:
    assert count("The fog had come in early.") == count("The fog had come in early.")
