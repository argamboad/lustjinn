"""Counting tokens the way the model does.

A budget is only worth keeping if it is measured in the model's own units. A characters-per-
token constant is not: Spanish and English differ by about 30%, and a budget that held in one
overflows in the other. `o200k_base` is the vocabulary the default model's family counts with,
and the one airp calibrated against a real transcript.
"""

from functools import lru_cache

import tiktoken

ENCODING = "o200k_base"

PER_MESSAGE = 4
"""What a message costs besides its text: the role and the separators the API wraps it in.
Measured against what the provider reported for a real transcript, not derived."""


@lru_cache
def encoding() -> tiktoken.Encoding:
    """The vocabulary, loaded once per process. tiktoken fetches it on first use and keeps a copy
    in its cache directory (`TIKTOKEN_CACHE_DIR`, or the system's temporary folder)."""
    return tiktoken.get_encoding(ENCODING)


def count(text: str) -> int:
    """Tokens in a piece of text. Special-token markers in the text count as ordinary text:
    a card that happens to contain one is still just a card."""
    return len(encoding().encode(text, disallowed_special=()))


def for_message(text: str) -> int:
    """Tokens one message costs in a prompt: its text plus the framing around it."""
    return count(text) + PER_MESSAGE
